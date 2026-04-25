figma.showUI(__html__, { width: 480, height: 520 });

function validateGeneratedScriptSource(source) {
  if (typeof source !== 'string') {
    throw new Error('Invalid input: source must be a string');
  }

  const cleaned = source.trim();

  if (cleaned === '') {
    throw new Error('Invalid input: source cannot be empty');
  }

  if (cleaned.includes('```')) {
    throw new Error('Invalid input: source contains markdown fences');
  }

  if (/^\s*(Here is|Sure|This code|The following|Explanation|To create)\b/i.test(cleaned)) {
    throw new Error('Invalid input: source appears to be prose, not executable JavaScript');
  }

  if (/^\s*(import|export)\b/m.test(cleaned)) {
    throw new Error('Invalid input: source contains ES module syntax');
  }

  if (cleaned.includes('figma.closePlugin(') || cleaned.includes('figma.root.remove(')) {
    throw new Error('Invalid input: source contains disallowed Figma API calls');
  }

  if (cleaned.includes('eval(') || cleaned.includes('new Function(')) {
    throw new Error('Invalid input: source contains nested dynamic execution');
  }

  return cleaned;
}

figma.ui.onmessage = async (msg) => {
  if (msg.type !== 'exec') return;

  try {
    const cleanedSource = validateGeneratedScriptSource(msg.code);

    // Build async function with Figma API in scope
    const fn = new Function(
      'figma',
      'print',
      `return (async () => { ${cleanedSource} })();`
    );

    const logs = [];
    const print = (...args) => {
      const text = args.map(a => typeof a === 'object' ? JSON.stringify(a, null, 2) : String(a)).join(' ');
      logs.push(text);
      figma.ui.postMessage({ type: 'log', text });
    };

    const result = await fn(figma, print);

    const output = logs.length > 0
      ? logs.join('\n')
      : result !== undefined
        ? String(result)
        : 'Done';

    figma.ui.postMessage({ type: 'result', text: output });
  } catch (e) {
    figma.ui.postMessage({ type: 'error', text: e.message || String(e) });
  }
};
