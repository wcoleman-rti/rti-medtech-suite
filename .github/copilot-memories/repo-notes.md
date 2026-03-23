# Medtech Suite — Repo Notes

## RTI Python Package Naming

- **pip package:** `rti.connext` (what goes in `requirements.txt`)
- **Runtime import:** `import rti.connextdds as dds` (the actual importable module)
- `import rti.connext` does NOT work — raises `ModuleNotFoundError`
- See INC-001 in `docs/agent/incidents.md` for full details
