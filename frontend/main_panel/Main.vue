<template>
  <MessageLog v-if="messagesMode"/>
  <MessageForm v-else-if="configureMessageMode" :key="messageType?.name"/>
</template>

<script setup>
  import { storeToRefs } from 'pinia'
  import { useUIStore } from '/frontend/stores/ui'
  import { useMessageStore } from '/frontend/stores/message'
  import MessageLog from './MessageLog.vue'
  import MessageForm from './message_form/MessageForm.vue'

  const { messagesMode, configureMessageMode } = storeToRefs(useUIStore())
  const { messageType } = storeToRefs(useMessageStore())
</script>

<style>
</style>
