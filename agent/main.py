"""Zip entrypoint for AgentCore Runtime direct code deployment (`entrypoint: ["main.py"]`)."""

from suppliagent_agent.app import app

if __name__ == "__main__":
    app.run()
