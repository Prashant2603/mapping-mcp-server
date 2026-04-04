# Copilot Studio Topic Blueprint: Create Mapping Set

This is a step-by-step blueprint for building the "Create Mapping Set" topic
in Copilot Studio. Build this as a Topic in the Copilot Studio UI.

## Topic Settings

- **Name**: Create Mapping Set
- **Trigger phrases**:
  - "create mapping"
  - "create a mapping set"
  - "generate mapping"
  - "new mapping set"
  - "new MS"
  - "map FormatA to FormatB" (pattern)

---

## Flow Nodes

### Node 1: Ask for Details (Question node)
- **Message**: "I'll help you create a new mapping set. Please provide:"
- **Question 1**: "What is the **source format**?" → Save to variable `sourceFormat`
- **Question 2**: "What is the **target format**?" → Save to variable `targetFormat`
- **Question 3** (optional): "Any description for this mapping?" → Save to variable `description`

---

### Node 2: Get Target Nodes (Action node — Plugin action)
- **Action**: Call MCP tool `list_target_nodes`
- **Inputs**:
  - `target_format` = `sourceFormat`
  - `source_format` = `targetFormat`
- **Save response to**: `targetNodesResult`

---

### Node 3: Present Overview (Message node)
- **Message** (use Adaptive Card or message with Power Fx):
```
I found {targetNodesResult.total_target_paths} target paths in
{length(targetNodesResult.nodes)} groups from
{length(targetNodesResult.reference_mapping_sets)} reference mapping sets.

Groups:
{For each node in targetNodesResult.nodes:}
  - {node.top_level_node} ({node.total_rules} rules) {if node.has_conflicts: "⚠️ has conflicts"}

I'll work through each group one by one. Starting with the first group.
```
- **Save**: Set variable `currentNodeIndex` = 0
- **Save**: Set variable `allApprovedRules` = "" (will accumulate XML)

---

### Node 4: Get Rules for Current Node (Action node — Plugin action)
- **Condition**: If `currentNodeIndex` < `length(targetNodesResult.nodes)`
  - **True** → Continue to action
  - **False** → Go to Node 8 (Assemble)

- **Action**: Call MCP tool `get_mapping_rules_for_node`
- **Inputs**:
  - `target_node` = `targetNodesResult.nodes[currentNodeIndex].top_level_node`
  - `target_format` = `targetFormat`
  - `source_format` = `sourceFormat`
- **Save response to**: `nodeRulesResult`

---

### Node 5: Present Rules (Condition + Message node)

#### Branch A: Rules found, NO conflicts
- **Condition**: `nodeRulesResult.total_rules_found > 0` AND `nodeRulesResult.conflicts` is empty
- **Message**:
```
**{nodeRulesResult.target_node}** — Found {nodeRulesResult.total_rules_found} rules from reference mapping sets:

{For each rule in nodeRulesResult.rules:}
```xml
{rule.candidates[0].xml}
```
{rule.candidates[0].description}

Do these look correct?
```
- **Question**: Yes / No / Modify
  - **Yes** → Append rules XML to `allApprovedRules`, go to Node 7
  - **No** → "What would you like to change?" → free text → Use Generative AI to modify, re-present
  - **Modify** → "Describe your changes:" → Use Generative AI to modify, re-present

#### Branch B: Rules found, WITH conflicts
- **Condition**: `nodeRulesResult.conflicts` is not empty
- **Message**:
```
**{nodeRulesResult.target_node}** — ⚠️ Conflict detected!

Multiple reference mapping sets handle these paths differently:

{For each rule in nodeRulesResult.rules where rule.has_conflict:}
**{rule.target_path}:**

Option A (from {rule.candidates[0].source_file}):
```xml
{rule.candidates[0].xml}
```

Option B (from {rule.candidates[1].source_file}):
```xml
{rule.candidates[1].xml}
```

Which approach do you prefer?
```
- **Question**: Option A / Option B / Custom
  - **A** → Use candidate[0], append to `allApprovedRules`
  - **B** → Use candidate[1], append to `allApprovedRules`
  - **Custom** → "Describe what you want:" → Use Generative AI

#### Branch C: No rules found
- **Condition**: `nodeRulesResult.total_rules_found == 0`
- **Message**: "No existing rules found for **{nodeRulesResult.target_node}**. Let me search for appropriate functions."
- **Action**: Call `search_functions` with query based on node name
- **Use Generative AI** to propose new rules based on function docs
- **Present** proposed rules → Ask for approval

---

### Node 6: Handle Function Lookup (if needed)
- Only reached from Branch C above
- **Action**: Call `search_functions(query=target_node_name)`
- **Use Generative AI** to generate mapping rules
- **Message**: "Here's what I suggest for {target_node}: [XML]. Does this look right?"
- **Question**: Yes / No → loop back to present

---

### Node 7: Next Node (Action node)
- **Set variable**: `currentNodeIndex` = `currentNodeIndex + 1`
- **Message**: "✓ {previous_node} approved. Moving to next group..."
- **Go to**: Node 4

---

### Node 8: Assemble Final Mapping Set (Message node)
- **Message**:
```
All nodes complete! Here's the assembled mapping set:

```xml
<?xml version="1.0"?>
<mappingSet>
  <id>{sourceFormat}_to_{targetFormat}</id>
  <sourceFormat>{sourceFormat}</sourceFormat>
  <targetFormat>{targetFormat}</targetFormat>
  <description>{description}</description>
  {allApprovedRules}
</mappingSet>
```

Would you like to make any changes?
```
- **Question**: Looks good / Make changes
  - **Looks good** → "Great! Your mapping set is ready. Copy the XML above."
  - **Make changes** → "Which section?" → loop back to relevant node

---

## Variables Summary

| Variable | Type | Purpose |
|----------|------|---------|
| `sourceFormat` | String | User-provided source format name |
| `targetFormat` | String | User-provided target format name |
| `description` | String | Optional description |
| `targetNodesResult` | Object | Response from list_target_nodes |
| `currentNodeIndex` | Number | Current position in node loop |
| `nodeRulesResult` | Object | Response from get_mapping_rules_for_node |
| `allApprovedRules` | String | Accumulated approved XML rules |

---

## Reduced Instructions (keep in agent instructions)

Since the topic handles the "Create Mapping Set" workflow, simplify the
agent instructions to only cover general behavior and the exploration workflow:

```
You help users explore, search, and generate XML mapping sets via MCP tools.
"MS" = mapping set.

Call tools when users ask to list, find, search, or inspect mapping data.
Skip tools for general questions or concepts you already know.

For creating new mapping sets, the "Create Mapping Set" topic handles the
full workflow. Do not attempt to create mapping sets outside that topic.

Show XML in ```xml code blocks. Understand: "SMRV4", "pain.001", "MS".
```

---

## Building Tips for Copilot Studio

1. **Plugin actions**: Each MCP tool appears as a plugin action once the MCP
   connector is configured. Drag them into action nodes.

2. **Looping**: Copilot Studio doesn't have native for-loops. Use a condition
   node that checks `currentNodeIndex < length(nodes)` and redirects back
   to the "Get Rules" node to simulate iteration.

3. **Generative AI nodes**: Use "Create generative answers" nodes for the
   parts where Copilot needs to reason (modifying rules, generating new ones
   from function docs). Pass the function docs and context as input.

4. **Adaptive Cards**: For the conflict presentation (Branch B), consider
   using an Adaptive Card with action buttons for cleaner UX.

5. **Testing**: Test each node independently in Copilot Studio's test pane
   before connecting them. Verify tool responses match expected variable shapes.
