<template>
  <h3>Scripts</h3>

  <div v-if="loading">Loading...</div>
  <div v-else-if="!scripts.length">No scripts loaded</div>

  <div v-for="script in scripts" :key="script.filename" class="script-item">
    <h4 :class="{ active: script.active }" @click="toggleExpanded(script.filename)">
      {{ script.active ? '>' : ' ' }} {{ script.name }}
    </h4>

    <div v-if="expanded[script.filename]" class="script-details">
      <p class="script-desc">{{ script.description }}</p>

      <div class="script-controls">
        <button v-if="!script.active" @click="activate(script.filename)">Activate</button>
        <button v-if="script.active" @click="reset(script.filename)">Reset</button>
      </div>

      <ul>
        <li v-for="step in script.steps" :key="step.name" class="step-item">
          <span class="step-name" :class="{ completed: script.completedSteps?.includes(step.name) }">
            {{ step.name }}
          </span>
          <span v-if="step.trigger" class="step-tag trigger">on: {{ step.trigger }}</span>
          <span v-if="step.after" class="step-tag after">after: {{ step.after }}</span>
          <button v-if="step.hasSend || step.hasResponse" class="edit-btn" @click="editStep(step)" title="Open in message form">
            Edit
          </button>
          <button v-if="step.hasSend || step.hasResponse" class="send-btn" @click="sendStep(script.filename, step.name)">
            Send
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup>
  import { ref, reactive, onMounted } from 'vue'
  import { useMessageStore } from '/frontend/stores/message'
  import { findProtoBy } from '/frontend/protobuf_service'

  const
    messageStore = useMessageStore(),
    scripts = ref([]),
    loading = ref(true),
    expanded = reactive({})

  const fetchScripts = async () => {
    try {
      const res = await fetch('/api/scripts')
      const data = await res.json()
      scripts.value = data.scripts
      // auto-expand active script
      for (const s of data.scripts) {
        if (s.active && expanded[s.filename] === undefined) expanded[s.filename] = true
      }
    } catch (e) {
      console.error('Failed to fetch scripts:', e)
    } finally {
      loading.value = false
    }
  }

  const toggleExpanded = (filename) => {
    expanded[filename] = !expanded[filename]
  }

  const activate = async (filename) => {
    await fetch(`/api/scripts/${filename}/activate`, { method: 'POST' })
    await fetchScripts()
  }

  const reset = async (filename) => {
    await fetch(`/api/scripts/${filename}/reset`, { method: 'POST' })
    await fetchScripts()
  }

  const sendStep = async (scriptFilename, stepName) => {
    const res = await fetch(`/api/scripts/${scriptFilename}/steps/${stepName}/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    })
    const data = await res.json()
    if (data.error) {
      alert(`Send failed: ${data.error}`)
    }
  }

  const editStep = (step) => {
    const data = step.send || step.response
    if (!data) return

    // Find BrokerToDevice proto type to open as form
    const b2dProto = findProtoBy({ name: 'BrokerToDevice' })
    if (!b2dProto) {
      console.error('BrokerToDevice proto not found')
      return
    }

    messageStore.loadFromData(b2dProto, data)
  }

  onMounted(fetchScripts)
</script>

<style>
  .script-item h4 {
    cursor: pointer;
    font-family: monospace;
  }

  .script-item h4.active {
    color: green;
    font-weight: bold;
  }

  .script-desc {
    font-size: 0.8em;
    color: gray;
    margin: 0 0 0.5em 0;
    white-space: normal;
  }

  .script-controls {
    margin-bottom: 0.5em;
  }

  .script-controls button {
    font-size: 0.8em;
    margin-right: 0.5em;
    cursor: pointer;
  }

  .step-item {
    display: flex;
    align-items: center;
    gap: 0.4em;
    flex-wrap: wrap;
    margin-bottom: 0.3em;
    white-space: normal;
    overflow-x: visible;
  }

  .step-name {
    font-family: monospace;
    font-size: 0.85em;
  }

  .step-name.completed {
    text-decoration: line-through;
    color: gray;
  }

  .step-tag {
    font-size: 0.7em;
    padding: 1px 4px;
    border-radius: 3px;
    font-family: monospace;
  }

  .step-tag.trigger {
    background: #e8f5e9;
    color: #2e7d32;
  }

  .step-tag.after {
    background: #e3f2fd;
    color: #1565c0;
  }

  .edit-btn, .send-btn {
    font-size: 0.7em;
    padding: 1px 6px;
    cursor: pointer;
    border-radius: 3px;
  }

  .edit-btn {
    background: #e3f2fd;
    border: 1px solid #1565c0;
    color: #1565c0;
  }

  .edit-btn:hover {
    background: #1565c0;
    color: white;
  }

  .send-btn {
    background: #fff3e0;
    border: 1px solid #ef6c00;
    color: #ef6c00;
  }

  .send-btn:hover {
    background: #ef6c00;
    color: white;
  }
</style>
