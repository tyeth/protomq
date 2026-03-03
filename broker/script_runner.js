/**
 * Script Runner - loads and executes playback scripts for ProtoMQ.
 *
 * Scripts are JSON files in the scripts/ directory that define sequences
 * of protobuf messages to send in response to device activity.
 *
 * Script format:
 * {
 *   "name": "Human-readable name",
 *   "description": "What this script tests",
 *   "protoVersion": "v2",
 *   "steps": [
 *     {
 *       "name": "step-id",
 *       "trigger": "checkin.request",     // execute when this field path exists in incoming message
 *       "response": { ... },              // reply on same topic (d2b->b2d)
 *     },
 *     {
 *       "name": "step-id-2",
 *       "after": "step-id",              // execute after named step completes
 *       "delay": 2000,                   // wait N ms after the "after" step
 *       "topic": "display",              // component topic to publish on
 *       "send": { ... },                 // BrokerToDevice payload
 *     }
 *   ]
 * }
 */
import { readdir, readFile } from 'fs/promises'
import { BrokerToDevice, DeviceToBroker } from "../protobufs.js"


/**
 * Load all scripts from the scripts/ directory.
 * Returns a Map of filename -> parsed script object.
 */
export const loadScripts = async (scriptsDir = 'scripts') => {
  const scripts = new Map()

  let files
  try {
    files = await readdir(scriptsDir)
  } catch (e) {
    console.log(`Scripts directory not found: ${scriptsDir}`)
    return scripts
  }

  for (const file of files) {
    if (!file.endsWith('.json')) continue
    try {
      const contents = (await readFile(`${scriptsDir}/${file}`)).toString()
      const script = JSON.parse(contents)
      scripts.set(file.replace('.json', ''), script)
      console.log(`  Loaded script: ${script.name} (${file})`)
    } catch (e) {
      console.warn(`  Failed to load script ${file}: ${e.message}`)
    }
  }

  return scripts
}


/**
 * Check if a decoded DeviceToBroker message matches a trigger pattern.
 * Trigger is a dot-separated field path, e.g., "checkin.request".
 * Returns true if traversing the path finds a truthy value.
 */
const matchesTrigger = (decodedMessage, trigger) => {
  const parts = trigger.split('.')
  let current = decodedMessage
  for (const part of parts) {
    if (current == null || typeof current !== 'object') return false
    current = current[part]
  }
  return current != null
}


/**
 * Extract the device prefix from a topic string.
 * e.g., "mydevice/ws-d2b/checkin/" -> "mydevice"
 */
const extractDevicePrefix = (topic) => topic.split('/')[0]


/**
 * Create a ScriptExecutor for a specific script.
 * Tracks execution state and handles step sequencing.
 */
export class ScriptExecutor {
  constructor(script, broker) {
    this.script = script
    this.broker = broker
    this.completedSteps = new Set()
    this.pendingTimers = []
    this.devicePrefix = null
  }

  get name() {
    return this.script.name
  }

  /**
   * Process an incoming D2B message. Returns true if a trigger matched.
   */
  handleMessage(decodedMessage, packet) {
    this.devicePrefix = extractDevicePrefix(packet.topic)

    for (const step of this.script.steps) {
      // Skip steps that don't have triggers (they're sequenced via "after")
      if (!step.trigger) continue

      // Skip already-completed trigger steps
      if (this.completedSteps.has(step.name)) continue

      if (matchesTrigger(decodedMessage, step.trigger)) {
        console.log(`[Script: ${this.script.name}] Trigger matched: "${step.name}" (${step.trigger})`)
        this._executeStep(step, packet)
        return true
      }
    }
    return false
  }

  /**
   * Execute a step: send response, mark complete, schedule follow-ups.
   */
  _executeStep(step, packet) {
    // Send response on same topic (if defined)
    if (step.response) {
      console.log(`[Script: ${this.script.name}] Sending response for "${step.name}"`)
      const encoded = BrokerToDevice.encode(step.response).finish()
      this.broker.publish({
        topic: packet.topic.replace('d2b', 'b2d'),
        payload: encoded
      })
    }

    // Send payload to specific topic (if defined)
    if (step.send && step.topic) {
      const topic = `${this.devicePrefix}/ws-b2d/${step.topic}/`
      console.log(`[Script: ${this.script.name}] Sending to ${topic} for "${step.name}"`)
      const encoded = BrokerToDevice.encode(step.send).finish()
      this.broker.publish({ topic, payload: encoded })
    }

    // Mark step complete
    this.completedSteps.add(step.name)

    // Schedule follow-up steps
    this._scheduleFollowUps(step.name)
  }

  /**
   * Find and schedule steps that should run after the given step.
   */
  _scheduleFollowUps(completedStepName) {
    for (const step of this.script.steps) {
      if (step.after !== completedStepName) continue
      if (this.completedSteps.has(step.name)) continue

      const delay = step.delay || 0
      console.log(`[Script: ${this.script.name}] Scheduling "${step.name}" in ${delay}ms`)

      const timer = setTimeout(() => {
        console.log(`[Script: ${this.script.name}] Executing "${step.name}"`)

        // Send payload to specific topic
        if (step.send && step.topic) {
          const topic = `${this.devicePrefix}/ws-b2d/${step.topic}/`
          console.log(`[Script: ${this.script.name}] Publishing to ${topic}`)
          const encoded = BrokerToDevice.encode(step.send).finish()
          this.broker.publish({ topic, payload: encoded })
        }

        // Send response on a topic derived from trigger context (if defined)
        if (step.response) {
          console.log(`[Script: ${this.script.name}] Sending response for "${step.name}"`)
          const encoded = BrokerToDevice.encode(step.response).finish()
          // For sequenced responses, we need a topic - use component topic
          if (step.topic) {
            const topic = `${this.devicePrefix}/ws-b2d/${step.topic}/`
            this.broker.publish({ topic, payload: encoded })
          }
        }

        this.completedSteps.add(step.name)
        this._scheduleFollowUps(step.name)
      }, delay)

      this.pendingTimers.push(timer)
    }
  }

  /**
   * Reset execution state (for re-running the script).
   */
  reset() {
    this.pendingTimers.forEach(t => clearTimeout(t))
    this.pendingTimers = []
    this.completedSteps.clear()
    this.devicePrefix = null
    console.log(`[Script: ${this.script.name}] Reset`)
  }
}


/**
 * Install the script runner on a broker.
 * Loads all scripts from the scripts/ directory and creates executors.
 * Returns the active executor (or null if no scripts loaded).
 */
export const installScriptRunner = async (broker, activeScriptName = null) => {
  console.log("Script Runner: Loading scripts...")
  const scripts = await loadScripts()

  if (scripts.size === 0) {
    console.log("Script Runner: No scripts found")
    return { scripts, activeExecutor: null }
  }

  console.log(`Script Runner: Loaded ${scripts.size} script(s)`)

  // Pick the active script
  let activeScript = null
  if (activeScriptName && scripts.has(activeScriptName)) {
    activeScript = scripts.get(activeScriptName)
  } else {
    // Default to first script
    const firstKey = scripts.keys().next().value
    activeScript = scripts.get(firstKey)
    activeScriptName = firstKey
  }

  console.log(`Script Runner: Active script: "${activeScript.name}" (${activeScriptName})`)

  const executor = new ScriptExecutor(activeScript, broker)

  return { scripts, activeExecutor: executor, activeScriptName }
}
