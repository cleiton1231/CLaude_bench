"""Catálogo de ferramentas simuladas (schemas OpenAI). Nada aqui executa algo real."""

from __future__ import annotations


def _fn(nome: str, desc: str, props: dict, obrig: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": nome, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": obrig}}}


S = {"type": "string"}
CATALOGO = {
    "obter_clima": _fn("obter_clima", "Clima atual de uma cidade.", {
        "cidade": {"type": "string", "description": "Nome da cidade"},
        "unidade": {"type": "string", "enum": ["celsius", "fahrenheit"], "description": "Padrão: celsius"},
    }, ["cidade"]),
    "converter_moeda": _fn("converter_moeda", "Converte valores entre moedas pela cotação do dia.", {
        "valor": {"type": "number"},
        "de": {"type": "string", "description": "Código ISO 4217 de origem, ex.: USD"},
        "para": {"type": "string", "description": "Código ISO 4217 de destino, ex.: BRL"},
    }, ["valor", "de", "para"]),
    "buscar_contato": _fn("buscar_contato", "Busca um contato na agenda pelo nome e retorna e-mail e telefone.", {
        "nome": S}, ["nome"]),
    "enviar_email": _fn("enviar_email", "Envia um e-mail.", {
        "para": {"type": "string", "description": "Endereço de e-mail do destinatário"},
        "assunto": S, "corpo": S,
    }, ["para", "assunto", "corpo"]),
    "agendar_evento": _fn("agendar_evento", "Cria um evento na agenda do usuário.", {
        "titulo": S,
        "data": {"type": "string", "description": "AAAA-MM-DD"},
        "hora": {"type": "string", "description": "HH:MM (24h)"},
        "duracao_min": {"type": "integer", "description": "Duração em minutos"},
    }, ["titulo", "data", "hora", "duracao_min"]),
    "executar_shell": _fn("executar_shell", "Executa um comando no terminal Linux do usuário.", {
        "comando": S}, ["comando"]),
    "consultar_pedido": _fn("consultar_pedido", "Consulta status de um pedido da loja.", {
        "id_pedido": S}, ["id_pedido"]),
    "calcular": _fn("calcular", "Avalia uma expressão aritmética com precisão.", {
        "expressao": S}, ["expressao"]),
    "buscar_documentos": _fn("buscar_documentos", "Busca na base interna de documentos da empresa.", {
        "consulta": S, "limite": {"type": "integer"}}, ["consulta"]),
}


def schemas(nomes: list[str]) -> list[dict]:
    return [CATALOGO[n] for n in nomes]


# --- ferramentas do modo agente (sistema de arquivos virtual) ---
AGENTE = {
    "listar_arquivos": _fn("listar_arquivos", "Lista todos os arquivos do projeto.", {}, []),
    "ler_arquivo": _fn("ler_arquivo", "Lê o conteúdo de um arquivo do projeto.", {"caminho": S}, ["caminho"]),
    "escrever_arquivo": _fn("escrever_arquivo",
                            "Sobrescreve (ou cria) um arquivo com o conteúdo completo informado.",
                            {"caminho": S, "conteudo": S}, ["caminho", "conteudo"]),
    "rodar_testes": _fn("rodar_testes", "Roda a suíte de testes do projeto (unittest) e devolve a saída.", {}, []),
    "executar_shell": CATALOGO["executar_shell"],
    "finalizar": _fn("finalizar", "Encerra a tarefa com um resumo/resposta final para o usuário.",
                     {"resposta": S}, ["resposta"]),
}
