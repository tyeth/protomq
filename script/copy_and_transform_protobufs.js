import { homedir } from 'os'
import { copyFile, lstat, mkdir, readdir, readFile, rm, writeFile } from 'fs/promises'
import { pbjs } from "protobufjs-cli"


const loadEnv = async () => {
  // load the file
  let envJSON
  try {
    envJSON = (await readFile('./.env.json')).toString()
  } catch(e) {
    if(e.message.includes("ENOENT")) {
      throw new Error("Did not find environment file: `.env.json`. Look at README.md for instructions.")
    }

   throw e
  }

  // parse the json
  let env
  try {
    env = JSON.parse(envJSON)
  } catch(e) {
    throw new Error("Environment file `env.json` is not valid JSON.")
  }

  // check the var we want is present
  if(!env?.protobufSource) {
    throw new Error("Did not find 'protobufSource' attribute in file .env.json!")
  }

  return env
}


// Parse a nanopb .options file into structured entries.
// Returns an array of { fqn, options } where fqn is the fully-qualified name
// and options is an object like { max_size: "32", submsg_callback: "true" }
const parseOptionsFile = (contents) => {
  const entries = []
  for (const rawLine of contents.split('\n')) {
    const line = rawLine.trim()
    // skip comments and blank lines
    if (!line || line.startsWith('#')) continue

    // format: "ws.display.Add.driver  max_size:32" (whitespace-separated, may have spaces around colon)
    const match = line.match(/^(\S+)\s+(.+)$/)
    if (!match) continue

    const fqn = match[1]
    const optionPairs = match[2].trim()
    const options = {}

    // parse key:value pairs — handles both "key:value" and "key: value" (space after colon)
    const pairRegex = /(\w+)\s*:\s*(\S+)/g
    let pairMatch
    while ((pairMatch = pairRegex.exec(optionPairs)) !== null) {
      const key = pairMatch[1]
      let value = pairMatch[2]
      // coerce numeric values to numbers, booleans to booleans
      if (value === 'true') value = true
      else if (value === 'false') value = false
      else if (/^\d+$/.test(value)) value = Number(value)
      options[key] = value
    }

    if (Object.keys(options).length > 0) {
      entries.push({ fqn, options })
    }
  }
  return entries
}


// Convert snake_case to camelCase (pbjs converts proto field names to camelCase in JSON output)
const snakeToCamel = (str) =>
  str.replace(/_([a-z0-9])/g, (_, ch) => ch.toUpperCase())


// Walk the nested bundle JSON to find a field or message by its fully-qualified name,
// then attach options. Returns true if successfully applied.
const applyOptionToBundle = (bundle, fqn, options) => {
  // Split fqn into parts, e.g. "ws.display.Add.driver" -> ["ws", "display", "Add", "driver"]
  const parts = fqn.split('.')

  // Try to resolve as a field first (all parts except last are namespace/message path)
  const resolveField = () => {
    let current = bundle
    for (let i = 0; i < parts.length - 1; i++) {
      if (current.nested?.[parts[i]]) {
        current = current.nested[parts[i]]
      } else {
        return null
      }
    }
    // current should be a message with "fields"
    // try both snake_case (original) and camelCase (pbjs converts to this)
    const rawFieldName = parts[parts.length - 1]
    const camelFieldName = snakeToCamel(rawFieldName)

    if (current.fields?.[rawFieldName]) {
      return current.fields[rawFieldName]
    }
    if (current.fields?.[camelFieldName]) {
      return current.fields[camelFieldName]
    }
    return null
  }

  // Try to resolve as a message (all parts are namespace/message path)
  const resolveMessage = () => {
    let current = bundle
    for (let i = 0; i < parts.length; i++) {
      if (current.nested?.[parts[i]]) {
        current = current.nested[parts[i]]
      } else {
        return null
      }
    }
    return current
  }

  const field = resolveField()
  if (field) {
    field.options = { ...field.options, ...options }
    return true
  }

  const message = resolveMessage()
  if (message) {
    message.options = { ...message.options, ...options }
    return true
  }

  return false
}


// wrap and call so we can use async/await
(async function() {
  console.log("Protobuf Import")

  console.log("Loading env.json...")
  const env = await loadEnv()

  const destination = "protobufs"
  console.log(`Cleaning destination: ${destination}`)

  // rm -rf protobufs && mkdir protobufs
  await rm(destination, { recursive: true, force: true })
  await mkdir(destination)

  // import from where? look up location
  const
    protobufRoot = env.protobufSource,
    protobufRootExpanded = protobufRoot.replace('~', homedir())

  console.log(`Copying .proto and .options files (recursively) from: ${protobufRootExpanded}`)

  const recursiveProtoCopy = async currentDirectory => {
    // list items in directory
    const items = await readdir(currentDirectory)

    for(const itemName of items) {
      const fullSourcePath = `${currentDirectory}/${itemName}`

      // skip nanopb
      if(itemName == "nanopb.proto") {
        // console.log("skip", itemName)

      // copy .proto and .options files
      } else if(itemName.endsWith('.proto') || itemName.endsWith('.options')) {
        // console.log("copy", itemName)
        const fullDestinationPath = `./${destination}/${itemName}`
        await copyFile(fullSourcePath, fullDestinationPath)

      // recurse into directories
      } else if((await lstat(fullSourcePath)).isDirectory()) {
        // console.log("recurse", itemName)
        await recursiveProtoCopy(fullSourcePath)

      // say what you're skipping
      } else {
        // console.log("skip", itemName)
      }
    }
  }

  await recursiveProtoCopy(protobufRootExpanded)

  console.log('Transforming .proto files...')

  // modifications to make to the proto files
  const replacements = [
    // no nanopb
    ['import "nanopb.proto";', '// nanopb import removed'],
    ['import "nanopb/nanopb.proto";', '// nanopb import removed'],
    // flatten import directories: "wippersnapper/file.proto" -> "file.proto"
    [/import "((?:\w*\/)+)\w*.proto";/g, (match, group) => match.replace(group, '')]
  ]

  // traverse the proto files in the destination (only .proto files need transformation)
  for(const filename of await readdir(destination)) {
    if (!filename.endsWith('.proto')) continue

    const
      // build the full path
      filePath = `./${destination}/${filename}`,
      // read the file into memory
      contents = (await readFile(filePath)).toString(),
      // apply all replacements
      replacedContents = replacements.reduce((acc, replaceArgs) => {
        return acc.replaceAll(...replaceArgs)
      }, contents)

    // overwrite the file
    await writeFile(filePath, replacedContents)
  }

  console.log('Processing *.proto files to bundle.json')

  pbjs.main([ "--target", "json", "protobufs/signal.proto" ], async (err, output) => {
    if (err) { throw err }

    const bundle = JSON.parse(output)

    // Parse .options files and merge nanopb metadata into the bundle
    console.log('Merging .options metadata into bundle...')
    const allFiles = await readdir(destination)
    const optionsFiles = allFiles.filter(f => f.endsWith('.options'))

    let appliedCount = 0
    let skippedCount = 0

    for (const optionsFile of optionsFiles) {
      const contents = (await readFile(`./${destination}/${optionsFile}`)).toString()
      const entries = parseOptionsFile(contents)

      for (const { fqn, options } of entries) {
        if (applyOptionToBundle(bundle, fqn, options)) {
          appliedCount++
        } else {
          console.warn(`  Could not resolve: ${fqn} (from ${optionsFile})`)
          skippedCount++
        }
      }
    }

    console.log(`  Applied ${appliedCount} option(s), ${skippedCount} unresolved`)

    await writeFile('protobufs/bundle.json', JSON.stringify(bundle, null, 2))
  })

  console.log('Done')
})()
