import { cloneDeep, compact, find, get, includes, set, some } from 'lodash-es'
import { ref } from "vue"
import { defineStore, acceptHMRUpdate } from 'pinia'
import { useUIStore } from './ui'
import { findProtoFor } from '../protobuf_service'

// detect and scrub array syntax
const scrubBrackets = pathSegment => {
  const bracketPosition = pathSegment.indexOf('[')

  return (bracketPosition > -1)
    ? pathSegment.slice(0, bracketPosition)
    : pathSegment
}

export const useMessageStore = defineStore('message', () => {
  return {
    messageObject: ref(null),
    messageType: ref(null),
    messageFields: ref(null),

    // caches fields from protobufs, so we can add/remove fields without
    // modifying the core protobuf info
    getFieldsAtPath: function(path='') {
      // cache hits return immediately
      if(this.messageFields[path]) { return this.messageFields[path] }

      let lastPath = ''
      path.split('.').forEach(pathSegment => {
        const currentPath = compact([lastPath, pathSegment]).join('.')

        if(!this.messageFields[currentPath]) {
          // look it up and set it
          const lastPathMessageFields = this.messageFields[scrubBrackets(lastPath)]
          const foundField = lastPathMessageFields.find(({ fieldName, fieldType, options=[] }) => {
            if(fieldType === 'oneof') {
              return some(options, { fieldName: scrubBrackets(pathSegment) })
            } else {
              return fieldName === scrubBrackets(pathSegment)
            }
          })

          if(!foundField) {
            console.warn('field not found:', pathSegment, lastPathMessageFields)
            this.messageFields[currentPath] = []

          } else {
            const toFind = (foundField.fieldType === 'oneof')
              ? find(foundField.options, { fieldName: scrubBrackets(pathSegment) })
              : foundField
            const protobuf = findProtoFor(toFind)
            if(!protobuf) {
              throw new Error(`Protobuf not found for: ${toFind}`)
            }

            // cache a copy of the fields in the protobuf
            this.messageFields[currentPath] = cloneDeep(protobuf.fields)
          }
        }

        lastPath = currentPath
      })

      return this.messageFields[lastPath]
    },

    // call when a OneOf selection changes
    setOneOf: function(path, selection) {
      // adds a new field based on the selection
      const peerPath = path.split('.').slice(0, -1).join('.')
      const selectionPath = compact([peerPath, selection.fieldName]).join('.')
      const fields = this.getFieldsAtPath(peerPath)
      fields.push(selection)
      // sets the data payload for the new field
      this.setDeep(path, selection.fieldName)
      this.setDeep(selectionPath, selection)
    },

    clearOneOf: function(path, unselection) {
      // remove it from the type fields
      const peerPath = path.split('.').slice(0, -1).join('.')
      const fields = this.getFieldsAtPath(peerPath)
      const indexToRemove = fields.indexOf(unselection)
      fields.splice(indexToRemove, 1)

      // remove it from the payload data
      const unselectedPath = compact([peerPath, unselection.fieldName]).join('.')
      this.setDeep(unselectedPath, undefined)

      // clear the top-level setting
      this.setDeep(path, null)
    },

    newMessage: function(messageType) {
      this.messageType = messageType
      this.messageObject = {}
      this.messageFields = {
        '': cloneDeep(messageType.fields)
      }

      this.setDefaults(this.messageType)

      // update the UI to edit this message
      useUIStore().setMode('configureMessage')
    },

    clearMessage: function() {
      this.messageType = null
      this.messageObject = null
      this.messageFields = null

      useUIStore().setMode('messages')
    },

    getDeep: function(pathToGet) {
      return get(this.messageObject, pathToGet)
    },

    setDeep: function(pathToSet, valueToSet, isArray=false) {
      if(valueToSet?.fieldType) {
        // set the given path to the given fieldname
        set(this.messageObject, pathToSet, isArray ? [valueToSet.fieldName] : valueToSet.fieldName)

        if(valueToSet.fieldType === 'message') {
          // make a new path at fieldname and recurse into setDefaults
          const pathItems = pathToSet.split('.')
          pathItems[pathItems.length -1] = valueToSet.fieldName
          const nextPath = pathItems.join('.')
          const protobuf = findProtoFor(valueToSet)
          this.setDefaults(protobuf, nextPath)
        } else {
          this.setDefault(valueToSet, pathToSet)
        }

        return
      }

      set(this.messageObject, pathToSet, isArray ? [valueToSet] : valueToSet)
    },

    popDeep: function(pathToRemove) {
      this.getDeep(pathToRemove).pop()
    },

    setDefault: function(field, path) {
      const isArray = field.rule === 'repeated'

      // nested message, look up the protobuf type and recurse
      if(field.fieldType === 'message') {
        this.setDeep(path, field, isArray)
        return
      }

      const defaultValue = defaultValueForField(field)

      if(defaultValue || defaultValue === false) {
        this.setDeep(path, defaultValue, isArray)
      } else {
        this.setDeep(path, null, isArray)
      }
    },

    setDefaults: function(type, pathPrefix=null) {
      // default all fields
      const { fieldPath } = type
      const fields = this.getFieldsAtPath(compact([pathPrefix, fieldPath]).join('.'))

      fields.forEach(field => {
        const path = compact([pathPrefix, fieldPath, field.fieldName]).join('.')

        this.setDefault(field, path)
      })
    }
  }
})

const DEFAULTS_BY_TYPE = {
  string: 'string',
  enum: 1,
  int32: '0',
  uint32: '0',
  float: '0.0',
  bool: false
}

const defaultValueForField = ({ type, fieldType, options }) => {
  // prefer nanopb default from .options files when present
  if(options?.default !== undefined) {
    return options.default
  }

  const recognizedTypes = Object.keys(DEFAULTS_BY_TYPE)

  return (includes(recognizedTypes, type)
    ? DEFAULTS_BY_TYPE[type]
    : DEFAULTS_BY_TYPE[fieldType])
}

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useMessageStore, import.meta.hot))
}
