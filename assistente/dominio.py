"""As regras do condomínio, em funções puras sobre uma conexão.

Toda função recebe o apartamento como argumento e nenhuma o adivinha: quem decide
esse valor é a camada de tools, que o lê do state da sessão. Aqui ficam as tabelas
de decisão — o que é recusado, com que frase, e o que nunca é dito.
"""

from __future__ import annotations

import re

from . import armazenamento

DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

FRASE_SEM_RESERVA = (
    "Não encontrei nenhuma reserva sua de {area} em {data}."
    " Só consigo cancelar reservas do seu próprio apartamento."
)


def _nome_da_area(conexao, identificador: str) -> str:
    area = armazenamento.buscar_area(conexao, identificador)
    return area["nome"] if area else identificador


def areas_disponiveis(conexao) -> dict:
    return {
        "areas": [
            {"id": a["id"], "nome": a["nome"], "taxa": a["taxa"]}
            for a in armazenamento.listar_areas(conexao)
        ]
    }


def nomes_das_areas(conexao) -> list[str]:
    return [a["nome"] for a in armazenamento.listar_areas(conexao)]


def disponibilidade(conexao, area: str, data: str) -> dict:
    """Livre ou ocupada, e nada além disso.

    A agenda inteira é olhada, como o enunciado permite, mas o dono da reserva
    nunca sai desta função — nem o código, nem o apartamento (Garantia 2).
    """
    alvo = armazenamento.buscar_area(conexao, area)
    if alvo is None:
        return {"erro": "area_inexistente", "areas": nomes_das_areas(conexao)}
    return {
        "area": alvo["nome"],
        "data": data,
        "disponivel": not armazenamento.data_ocupada(conexao, area, data),
    }


def exige_cobranca(conexao, area: str) -> bool:
    """Taxa maior que zero gera cobrança, e cobrança exige confirmação."""
    alvo = armazenamento.buscar_area(conexao, area)
    return bool(alvo) and float(alvo["taxa"]) > 0


def reservar(conexao, apartamento: str, area: str, data: str) -> dict:
    """Grava a reserva, ou recusa dizendo o mínimo que resolve o pedido."""
    alvo = armazenamento.buscar_area(conexao, area)
    if alvo is None:
        return {
            "ok": False,
            "motivo": "area_inexistente",
            "mensagem": (
                "Não existe essa área no condomínio. As áreas comuns são: "
                + ", ".join(nomes_das_areas(conexao))
                + "."
            ),
        }
    if not DATA.match(data or ""):
        return {
            "ok": False,
            "motivo": "data_invalida",
            "mensagem": "Preciso da data no formato AAAA-MM-DD.",
        }

    if armazenamento.reserva_propria(conexao, apartamento, area, data):
        return {
            "ok": False,
            "motivo": "ja_e_sua",
            "mensagem": f"A reserva de {alvo['nome']} em {data} já é sua.",
        }

    try:
        codigo = armazenamento.gravar_reserva(conexao, apartamento, area, data)
    except armazenamento.DataIndisponivel:
        # A recusa veio do índice único no commit. É a mesma resposta do caso em
        # que a agenda já aparecia ocupada: o morador não fica sabendo de quem é.
        return {
            "ok": False,
            "motivo": "indisponivel",
            "mensagem": f"{alvo['nome']} não está disponível em {data}.",
        }
    return {
        "ok": True,
        "codigo": codigo,
        "area": alvo["nome"],
        "data": data,
        "mensagem": f"Reserva confirmada: {alvo['nome']} em {data}, código {codigo}.",
    }


def cancelar(conexao, apartamento: str, area: str, data: str) -> dict:
    """Cancela a reserva do próprio apartamento; qualquer outro caso é a mesma frase.

    Reserva de terceiro e reserva inexistente respondem idêntico de propósito:
    distinguir os dois revelaria que a reserva alheia existe (Garantia 2).
    """
    codigo = armazenamento.cancelar_reserva(conexao, apartamento, area, data)
    if codigo is None:
        return {
            "ok": False,
            "motivo": "sem_reserva_sua",
            "mensagem": FRASE_SEM_RESERVA.format(
                area=_nome_da_area(conexao, area), data=data
            ),
        }
    return {
        "ok": True,
        "codigo": codigo,
        "mensagem": (
            f"Reserva {codigo} de {_nome_da_area(conexao, area)} em {data} cancelada."
        ),
    }


def minhas_reservas(conexao, apartamento: str) -> dict:
    return {"reservas": armazenamento.reservas_do_apartamento(conexao, apartamento)}


def autorizar_visitante(conexao, apartamento: str, nome: str, data: str) -> dict:
    """Registra a autorização sempre no apartamento recebido, nunca no citado."""
    nome = (nome or "").strip()
    if not nome:
        return {
            "ok": False,
            "motivo": "sem_nome",
            "mensagem": "Preciso do nome de quem vai entrar.",
        }
    if not DATA.match(data or ""):
        return {
            "ok": False,
            "motivo": "data_invalida",
            "mensagem": "Preciso da data da visita no formato AAAA-MM-DD.",
        }
    armazenamento.gravar_visitante(conexao, apartamento, nome, data)
    return {
        "ok": True,
        "nome": nome,
        "data": data,
        "mensagem": f"Entrada de {nome} autorizada para {data}.",
    }


def meus_visitantes(conexao, apartamento: str) -> dict:
    return {"visitantes": armazenamento.visitantes_do_apartamento(conexao, apartamento)}
