"""Banco SQLite do condomínio: estrutura, semeadura a partir de `dados/` e gravações.

A exclusividade de área e data não é conferência prévia: é o índice único parcial
`reservas_area_data_ativa`, que recusa a segunda gravação no instante do commit
(Garantia 5). A conferência de agenda que o domínio faz antes é conveniência para
o morador e nunca a garantia.
"""

from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path

ESTRUTURA = """
CREATE TABLE IF NOT EXISTS apartamentos (
    numero  TEXT PRIMARY KEY,
    morador TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS areas (
    id   TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    taxa REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS reservas (
    codigo      TEXT PRIMARY KEY,
    apartamento TEXT NOT NULL REFERENCES apartamentos(numero),
    area        TEXT NOT NULL REFERENCES areas(id),
    data        TEXT NOT NULL,
    ativa       INTEGER NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS reservas_area_data_ativa
    ON reservas(area, data) WHERE ativa = 1;

CREATE TABLE IF NOT EXISTS visitantes (
    apartamento TEXT NOT NULL REFERENCES apartamentos(numero),
    nome        TEXT NOT NULL,
    data        TEXT NOT NULL
);
"""

INDICE_DE_EXCLUSIVIDADE = "reservas_area_data_ativa"
TENTATIVAS_DE_CODIGO = 50


class DataIndisponivel(RuntimeError):
    """O banco recusou a gravação: a área já tem reserva ativa naquela data."""


def conectar(caminho: Path) -> sqlite3.Connection:
    """Abre o banco com as pragmas que a disputa do passo 14 exige.

    `busy_timeout` faz o segundo gravador esperar em vez de errar na hora, e é o
    que garante que ele chegue até o índice único e receba a recusa correta.
    """
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conexao = sqlite3.connect(caminho, timeout=5.0, isolation_level=None)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA journal_mode = WAL")
    conexao.execute("PRAGMA foreign_keys = ON")
    conexao.execute("PRAGMA busy_timeout = 5000")
    return conexao


def criar_estrutura(conexao: sqlite3.Connection) -> None:
    conexao.executescript(ESTRUTURA)


def semear(conexao: sqlite3.Connection, diretorio_de_dados: Path) -> None:
    """Carrega as quatro tabelas a partir dos arquivos imutáveis de `dados/`.

    O índice único parcial já existe quando isto roda, sobre tabela vazia; as três
    reservas semeadas são únicas por (`area`, `data`), então a semeadura passa.
    """

    def ler(nome: str) -> list[dict]:
        return json.loads((diretorio_de_dados / nome).read_text(encoding="utf-8"))

    conexao.execute("BEGIN IMMEDIATE")
    try:
        conexao.executemany(
            "INSERT INTO apartamentos (numero, morador) VALUES (?, ?)",
            [(a["numero"], a["morador"]) for a in ler("apartamentos.json")],
        )
        conexao.executemany(
            "INSERT INTO areas (id, nome, taxa) VALUES (?, ?, ?)",
            [(a["id"], a["nome"], float(a["taxa"])) for a in ler("areas.json")],
        )
        conexao.executemany(
            "INSERT INTO reservas (codigo, apartamento, area, data, ativa)"
            " VALUES (?, ?, ?, ?, 1)",
            [
                (r["codigo"], r["apartamento"], r["area"], r["data"])
                for r in ler("reservas.json")
            ],
        )
        conexao.executemany(
            "INSERT INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)",
            [
                (v["apartamento"], v["nome"], v["data"])
                for v in ler("visitantes.json")
            ],
        )
        conexao.execute("COMMIT")
    except Exception:
        conexao.execute("ROLLBACK")
        raise


def preparar(caminho: Path, diretorio_de_dados: Path) -> None:
    """Garante banco pronto antes da primeira requisição, semeando se ele não existir."""
    existia = caminho.exists()
    conexao = conectar(caminho)
    try:
        criar_estrutura(conexao)
        if not existia or not conexao.execute(
            "SELECT 1 FROM apartamentos LIMIT 1"
        ).fetchone():
            semear(conexao, diretorio_de_dados)
    finally:
        conexao.close()


def restaurar(
    caminho_do_condominio: Path, caminho_das_sessoes: Path, diretorio_de_dados: Path
) -> None:
    """Descarta o banco do condomínio e as sessões, e volta ao estado de `dados/`.

    Apagar o arquivo em vez de limpar as tabelas é o que torna a restauração
    idempotente: um banco pela metade de uma execução interrompida desaparece junto.
    """
    for arquivo in (caminho_do_condominio, caminho_das_sessoes):
        for sufixo in ("", "-wal", "-shm"):
            candidato = arquivo.with_name(arquivo.name + sufixo)
            candidato.unlink(missing_ok=True)

    conexao = conectar(caminho_do_condominio)
    try:
        criar_estrutura(conexao)
        semear(conexao, diretorio_de_dados)
    finally:
        conexao.close()


def _gerar_codigo(conexao: sqlite3.Connection) -> str:
    """Sorteia um código ainda não usado na tabela inteira, canceladas incluídas.

    `codigo` é PRIMARY KEY de `reservas` e cancelar nunca apaga a linha, então um
    código já emitido continua ocupado para sempre (regra de negócio 5).
    """
    for _ in range(TENTATIVAS_DE_CODIGO):
        codigo = f"RSV-{random.randint(1000, 9999)}"
        existe = conexao.execute(
            "SELECT 1 FROM reservas WHERE codigo = ?", (codigo,)
        ).fetchone()
        if not existe:
            return codigo
    raise RuntimeError("Não foi possível gerar um código de reserva inédito.")


def gravar_reserva(
    conexao: sqlite3.Connection, apartamento: str, area: str, data: str
) -> str:
    """Grava uma reserva ativa e devolve o código, ou recusa se a data já foi tomada.

    A recusa vem do índice único no commit, nunca de uma leitura feita antes: é por
    isso que duas aprovações simultâneas para a mesma área e data não podem ambas
    vencer, por mais próximas que cheguem.
    """
    conexao.execute("BEGIN IMMEDIATE")
    try:
        codigo = _gerar_codigo(conexao)
        conexao.execute(
            "INSERT INTO reservas (codigo, apartamento, area, data, ativa)"
            " VALUES (?, ?, ?, ?, 1)",
            (codigo, apartamento, area, data),
        )
        conexao.execute("COMMIT")
        return codigo
    except sqlite3.IntegrityError as erro:
        conexao.execute("ROLLBACK")
        if INDICE_DE_EXCLUSIVIDADE in str(erro):
            raise DataIndisponivel(area, data) from erro
        raise
    except Exception:
        conexao.execute("ROLLBACK")
        raise


def cancelar_reserva(
    conexao: sqlite3.Connection, apartamento: str, area: str, data: str
) -> str | None:
    """Marca como cancelada a reserva ativa daquele apartamento, e devolve o código.

    O `WHERE apartamento = ?` é o que impede cancelar reserva alheia: a consulta não
    enxerga fora do apartamento da sessão, então não há o que vazar para a resposta.
    """
    conexao.execute("BEGIN IMMEDIATE")
    try:
        linha = conexao.execute(
            "SELECT codigo FROM reservas"
            " WHERE apartamento = ? AND area = ? AND data = ? AND ativa = 1",
            (apartamento, area, data),
        ).fetchone()
        if linha is None:
            conexao.execute("COMMIT")
            return None
        conexao.execute(
            "UPDATE reservas SET ativa = 0 WHERE codigo = ?", (linha["codigo"],)
        )
        conexao.execute("COMMIT")
        return linha["codigo"]
    except Exception:
        conexao.execute("ROLLBACK")
        raise


def gravar_visitante(
    conexao: sqlite3.Connection, apartamento: str, nome: str, data: str
) -> None:
    conexao.execute("BEGIN IMMEDIATE")
    try:
        conexao.execute(
            "INSERT INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)",
            (apartamento, nome, data),
        )
        conexao.execute("COMMIT")
    except Exception:
        conexao.execute("ROLLBACK")
        raise


def apartamento_existe(conexao: sqlite3.Connection, numero: str) -> bool:
    return (
        conexao.execute(
            "SELECT 1 FROM apartamentos WHERE numero = ?", (numero,)
        ).fetchone()
        is not None
    )


def listar_areas(conexao: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conexao.execute("SELECT id, nome, taxa FROM areas ORDER BY rowid"))


def buscar_area(conexao: sqlite3.Connection, identificador: str) -> sqlite3.Row | None:
    return conexao.execute(
        "SELECT id, nome, taxa FROM areas WHERE id = ?", (identificador,)
    ).fetchone()


def data_ocupada(conexao: sqlite3.Connection, area: str, data: str) -> bool:
    """Devolve só livre ou ocupada — nunca de quem é a reserva (Garantia 2)."""
    return (
        conexao.execute(
            "SELECT 1 FROM reservas WHERE area = ? AND data = ? AND ativa = 1",
            (area, data),
        ).fetchone()
        is not None
    )


def reserva_propria(
    conexao: sqlite3.Connection, apartamento: str, area: str, data: str
) -> sqlite3.Row | None:
    return conexao.execute(
        "SELECT codigo FROM reservas"
        " WHERE apartamento = ? AND area = ? AND data = ? AND ativa = 1",
        (apartamento, area, data),
    ).fetchone()


def reservas_do_apartamento(
    conexao: sqlite3.Connection, apartamento: str
) -> list[dict]:
    linhas = conexao.execute(
        "SELECT codigo, area, data FROM reservas"
        " WHERE apartamento = ? AND ativa = 1 ORDER BY data, codigo",
        (apartamento,),
    )
    return [
        {"codigo": l["codigo"], "area": l["area"], "data": l["data"]} for l in linhas
    ]


def visitantes_do_apartamento(
    conexao: sqlite3.Connection, apartamento: str
) -> list[dict]:
    linhas = conexao.execute(
        "SELECT nome, data FROM visitantes WHERE apartamento = ? ORDER BY data, nome",
        (apartamento,),
    )
    return [{"nome": l["nome"], "data": l["data"]} for l in linhas]
