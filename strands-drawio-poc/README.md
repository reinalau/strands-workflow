# strands-drawio-poc

Prueba de concepto aislada: ¿puede un `Agent` de Strands usar el MCP server de
draw.io (`@drawio/mcp`) como tool y generar un diagrama de arquitectura AWS
válido, que permita abrir en el editor web de draw.io?

**No es parte del proyecto `discovery-meeting-workflow`.** No usa la tool
`workflow` a propósito — el objetivo acá es aislar y validar solo la
integración con el MCP, antes de decidir cómo (o si) conectarla a la Fase 2
de ese proyecto.

## Prerequisitos

- **Node.js >= 18** (`node --version`) — el MCP server corre vía `npx @drawio/mcp`
- Python 3.12+
- Ollama local con el modelo bajado, o `GEMINI_API_KEY`

## Instalación

```bash
pip install -r requirements.txt
cp .env.example .env
```

Editá `.env` con tu `MODEL_PROVIDER` preferido.

## Ejecución

```bash
python main.py
```

Debería:
1. Listar las tools del MCP (`open_drawio_xml`, `open_drawio_csv`, `open_drawio_mermaid`)
2. El agente genera una arquitectura serverless simple y llama a `open_drawio_xml`
3. La tool devuelve una URL — abrila en el browser para ver el diagrama en app.diagrams.net

## Qué verificar al correrlo

- [ ] ¿La tool list se lista correctamente? (confirma que la conexión stdio con `npx` funciona)
- [ ] ¿El agente efectivamente llama a la tool, o solo describe la arquitectura en texto?
- [ ] ¿El XML generado es válido — abre sin error en draw.io?
- [ ] ¿Usa shapes de AWS reales, o cuadros genéricos? (no está garantizado sin un prompt más específico)

## Notas de diseño

- `build_model()` construye el objeto `Model` directamente (`OllamaModel`/`LiteLLMModel`)
  para pasarlo a `Agent(model=...)` — distinto de cómo se configura un provider
  dentro de una `task` del `workflow` tool (ahí se usa `model_provider`/`model_settings`
  como strings/dicts, resueltos por el dispatcher interno `create_model` de
  `strands_tools`). Acá no hay `workflow` de por medio, así que se instancia
  el `Model` real, tal como lo pide la firma de `Agent()`.
- Mismo detalle de `LiteLLMModel` vs `OllamaModel` que en el proyecto principal:
  Ollama acepta `temperature`/`max_tokens` planos, LiteLLM los quiere anidados
  bajo `params`.
