<template>
  <div class="message-form">
    <h3>{{ messageType.name }}</h3>

    <blockquote class="description">
      {{ messageType.comment }}
    </blockquote>

    <!-- TODO: repeated -->

    <label class="label">
      <p>Topic:</p>
      <button @click="toggleManualTopic">x</button>
      <input v-if="manualTopic" class="topic-input" type="text" v-model="topicValue"/>
      <select v-else v-model="topicValue">
        <option v-for="subscription in topicOptions" :value="subscription">{{ subscription }}</option>
      </select>
    </label>

    <FieldInput v-for="field in messageFields['']" :field="field" :key="messageType.name + '.' + field.fieldName"/>

    <div class="action-bar">
      <button @click="setMode('messages')">Cancel</button>
      <button @click="publishMessage">Publish</button>
    </div>

    <label class="nanopb-toggle">
      <input type="checkbox" v-model="enforceNanopbLimits"/>
      Enforce nanopb limits
    </label>

    <div>
      <h4>Debug: Protobuf Payload</h4>
      <pre>{{ messageObject }}</pre>
    </div>
  </div>
</template>

<script setup>
  import { ref, computed } from 'vue'
  import { flatMap, uniq } from 'lodash-es'
  import { useUIStore } from '/frontend/stores/ui'
  import { useMessageStore } from '/frontend/stores/message'
  import { useSubscriptionStore } from '/frontend/stores/subscriptions'
  import { storeToRefs } from 'pinia'
  import FieldInput from './FieldInput.vue'
  import { encodeByName, envelopeLookup } from '/frontend/protobuf_service'
  import { useMQTTStore } from '/frontend/stores/mqtt'
  import { topicToMessageName } from '/frontend/util'

  const
    messageStore = useMessageStore(),
    mqttStore = useMQTTStore(),
    uiStore = useUIStore(),
    { setMode } = uiStore,
    { enforceNanopbLimits } = storeToRefs(uiStore),
    { messageObject, messageType, messageFields } = storeToRefs(messageStore),
    { clearMessage } = messageStore,
    { filteredSubscriptions } = storeToRefs(useSubscriptionStore()),
    topicOptions = computed(() => uniq(flatMap(filteredSubscriptions.value, sub => (
      [ sub, sub.replace('b2d', 'd2b'), sub.replace('d2b', 'b2d')]
    )))),
    topicValue = ref(filteredSubscriptions.value[0]),
    manualTopic = ref(!topicValue.value),
    toggleManualTopic = () => manualTopic.value = !manualTopic.value,
    publishMessage = () => {
      // validate nanopb limits if enforcement is on
      if(enforceNanopbLimits.value) {
        const violations = validateNanopbLimits(messageObject.value, messageFields.value)
        if(violations.length) {
          alert(`Nanopb limit violations:\n\n${violations.join('\n')}`)
          return
        }
      }

      const
        topic = topicValue.value,
        messageName = messageType.value.name,
        messagePayload = messageObject.value,
        { envelopeMessage } = envelopeLookup(messageName, messagePayload),
        messageNameByTopic = topicToMessageName(topic)

      if(messageNameByTopic !== envelopeMessage.name) {
        alert(`Message envelope mismatch!\nTopic expected: ${messageNameByTopic}\nMessage expected: ${envelopeMessage.name}`)
        return
      }

      // protobuf form encode and send PoC working right here
      const encodedMessage = encodeByName(messageName, messagePayload)
      mqttStore.publishMessage(topicValue.value, encodedMessage)
      clearMessage()
    }

  // recursively validate nanopb limits against the message payload
  const validateNanopbLimits = (obj, fieldsByPath, path='') => {
    const violations = []
    if(!obj || typeof obj !== 'object') return violations

    const fields = fieldsByPath[path] || []

    for(const field of fields) {
      const value = obj[field.fieldName]
      const fieldLabel = path ? `${path}.${field.fieldName}` : field.fieldName

      // max_size: string length limit
      if(field.options?.max_size && typeof value === 'string') {
        if(value.length > field.options.max_size) {
          violations.push(`${fieldLabel}: length ${value.length} exceeds max_size ${field.options.max_size}`)
        }
      }

      // max_count: repeated field item limit
      if(field.options?.max_count && Array.isArray(value)) {
        if(value.length > field.options.max_count) {
          violations.push(`${fieldLabel}: ${value.length} items exceeds max_count ${field.options.max_count}`)
        }
      }

      // recurse into nested messages
      if(field.fieldType === 'message' && value && typeof value === 'object') {
        const nextPath = fieldLabel
        violations.push(...validateNanopbLimits(value, fieldsByPath, nextPath))
      }
    }

    return violations
  }
</script>

<style>
  .message-form {
    max-width: 500px;
  }

  .description {
    font-style: italic;
    color: gray;
  }

  .topic-input {
    width: 100%;
  }

  .label {
    display: flex;
    gap: 1em;
    font-family: monospace;
  }

  .label p {
    min-width: 150px;
    text-align: right;
  }

  .action-bar {
    margin-top: 2em;
    max-width: 500px;
    display: flex;
    gap: 1em;
    justify-content: space-around;
  }

  .action-bar button {
    font-size: 1.5em;
    font-weight: 600;
    color: white;
    background-color: hsl(31, 28%, 53%);
    padding: 10px 15px;
    border-radius: 15px;
  }

  .action-bar button:hover {
    cursor: pointer;
    background-color: hsl(31, 28%, 45%);
  }

  .nanopb-toggle {
    display: flex;
    align-items: center;
    gap: 0.5em;
    margin-top: 1em;
    font-size: 0.9em;
    color: gray;
    cursor: pointer;
    user-select: none;
  }

  .nanopb-toggle input[type="checkbox"] {
    cursor: pointer;
  }
</style>
