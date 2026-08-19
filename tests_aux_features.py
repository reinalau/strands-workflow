# pip install strands-agents strands-agents-tools
from strands import Agent
from strands_tools import workflow

agent = Agent(tools=[workflow], callback_handler=None)

# Crear un workflow simple (no llama al LLM)
agent.tool.workflow(
    action="create",
    workflow_id="demo_test",
    tasks=[
        {"task_id": "step1", "description": "Say hello"},
        {"task_id": "step2", "description": "Say goodbye", "dependencies": ["step1"]},
    ]
)

# Probar pause / resume
print(agent.tool.workflow(action="pause", workflow_id="demo_test"))
print(agent.tool.workflow(action="resume", workflow_id="demo_test"))

# Limpieza
agent.tool.workflow(action="delete", workflow_id="demo_test")