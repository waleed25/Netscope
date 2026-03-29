---
name: skill-creator
description: >
  Create, edit, list, or delete Netscope skills (SKILL.md files) dynamically.
  Skills are instruction files that teach the agent how to handle specific tasks.
  Use when user wants to create a new skill, add a capability, define a workflow,
  edit an existing skill, list available skills, or remove a skill.
license: Proprietary
metadata:
  category: meta
  triggers:
    - create skill
    - new skill
    - add skill
    - edit skill
    - list skills
    - delete skill
    - remove skill
    - what skills
    - show skills
    - skill management
    - define workflow
    - teach the agent
  tool_sequence:
    - list_skills
    - create_skill
    - update_skill
    - delete_skill
    - reload_skills
  examples:
    - "Create a new skill for analyzing HTTP traffic"
    - "Show me all available skills"
    - "Edit the modbus-analysis skill"
    - "Delete the test skill"
    - "Add a skill for analyzing DNS exfiltration"
---

## Skill Creator Workflow

### Create a new skill

Use the `create_skill` tool with the skill content in SKILL.md format:

```
TOOL: create_skill http-analysis
```

The skill body follows the standard SKILL.md format:

```yaml
---
name: http-analysis
description: >
  Analyze HTTP traffic for web application attacks, suspicious requests,
  data exfiltration over HTTP, and API abuse.
metadata:
  triggers: [http, web, request, response, api, url]
  tool_sequence: [query_packets, tshark_filter, expert_analyze]
---

## HTTP Analysis Instructions
...
```

### List skills
`list_skills` — shows all loaded skills with name, description, and trigger count

### Edit a skill
`update_skill <name>` — provide the new content; the file is overwritten and reloaded

### Delete a skill
`delete_skill <name>` — removes the skill file and unloads from registry

### Reload skills
`reload_skills` — re-scans the skills directory without restarting the backend

### SKILL.md format reference

**Required fields:**
- `name`: kebab-case identifier (max 64 chars)
- `description`: what the skill does + when to use it (this is the trigger condition)

**Optional metadata extensions:**
- `triggers`: list of keywords that activate this skill
- `tool_sequence`: recommended tool call order
- `examples`: sample user queries that should trigger this skill

**Body**: Markdown instructions for the agent. Include:
- Step-by-step workflow
- Tool usage examples with parameters
- Interpretation guidance
- Domain knowledge and reference tables
