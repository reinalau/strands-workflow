"""
POC: Agent + drawio MCP as a tool.

Goal: verify that a Strands Agent, given the drawio MCP server (@drawio/mcp,
via npx/stdio), can generate a valid draw.io XML diagram from a natural
language architecture description, and that the returned URL opens correctly
in the browser (app.diagrams.net).

This is a standalone proof of concept — NOT part of the discovery-meeting-
workflow project. No `workflow` tool involved here on purpose: this tests
whether the MCP integration itself works before deciding how (or if) to wire
it into the main project's "architecture proposal" phase.

Prerequisites:
    - Node.js >= 18 installed (`node --version`)
    - Python 3.12+, `pip install -r requirements.txt`
    - Ollama running locally with the model pulled, OR GEMINI_API_KEY set

Usage:
    python main.py
"""

import os

from dotenv import load_dotenv

load_dotenv()

from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client
from strands import Agent
from strands.tools.mcp import MCPClient

MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "ollama").lower()


def build_model():
    """Build an actual Model object for Agent(model=...). Unlike the
    workflow tool's internal create_model(provider=..., config=...)
    dispatcher, Agent() itself takes a Model instance directly."""
    if MODEL_PROVIDER == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY is not set.")
        os.environ.setdefault("GEMINI_API_KEY", api_key)
        from strands.models.litellm import LiteLLMModel

        return LiteLLMModel(
            model_id=f"gemini/{os.getenv('GEMINI_MODEL_ID', 'gemini-2.0-flash')}",
            # NOTE: unlike OllamaModel (flat kwargs, see below), LiteLLMModel's
            # own validation only accepts: context_window_limit, model_id,
            # params, stream — temperature/max_tokens must be nested under
            # "params" (verified in the sibling discovery-meeting-workflow
            # project against the exact same UserWarning).
            params={"temperature": 0.4, "max_tokens": 4096},
        )

    from strands.models.ollama import OllamaModel

    return OllamaModel(
        host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        model_id=os.getenv("OLLAMA_MODEL_ID", "gemma4:e2b-it-qat"),
        temperature=0.4,
        max_tokens=4096,
        options={"num_ctx": 12288},
    )


ARCHITECTURE_PROMPT = (
    "Sos un AWS Solutions Architect. Proponé una arquitectura AWS serverless "
    "simple para una PyME que quiere migrar un backend monolítico on-premise "
    "a la nube, priorizando bajo costo operativo. Componentes sugeridos: "
    "API Gateway, Lambda, DynamoDB, S3 para assets estáticos, CloudFront.\n\n"
    "Generá el diagrama de esta arquitectura usando la tool de draw.io "
    "disponible (XML), con los iconos de aws, con los componentes conectados en el flujo lógico "
    "correcto (cliente -> CloudFront -> API Gateway -> Lambda -> DynamoDB)."
)


def main():
    drawio_mcp = MCPClient(
        lambda: stdio_client(StdioServerParameters(command="npx", args=["-y", "@drawio/mcp"]))
    )

    with drawio_mcp:
        tools = drawio_mcp.list_tools_sync()
        print(f"Tools disponibles del MCP drawio: {[t.tool_name for t in tools]}")

        agent = Agent(
            tools=tools,
            system_prompt="Sos un asistente que diseña arquitecturas AWS y las diagrama con draw.io en el formato XML. Cuando termines, abrir la herramienta web de drawio con el diagrama generado",
            model=build_model(),
        )

        result = agent(ARCHITECTURE_PROMPT)
        print("\n=== RESULTADO ===")
        print(result)


if __name__ == "__main__":
    main()
