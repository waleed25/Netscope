export interface ParsedA2UI {
  type: string;
  props: Record<string, any>;
  raw: string;
}

const A2UI_PATTERN = /\x00A2UI:({.*?})\x00/gs;

export function parseA2UIChunks(chunks: string[]): ParsedA2UI[] {
  const results: ParsedA2UI[] = [];
  
  for (const chunk of chunks) {
    const matches = chunk.matchAll(A2UI_PATTERN);
    for (const match of matches) {
      try {
        const parsed = JSON.parse(match[1]);
        results.push({
          type: parsed.type,
          props: parsed.props || {},
          raw: match[0],
        });
      } catch (e) {
        console.warn('Failed to parse A2UI:', match[1]);
      }
    }
  }
  
  return results;
}

export function extractA2UIMessage(message: string): { 
  a2ui: ParsedA2UI | null; 
  markdown: string 
} {
  const a2uiMatches = message.match(A2UI_PATTERN);
  
  if (!a2uiMatches || a2uiMatches.length === 0) {
    return { a2ui: null, markdown: message };
  }
  
  // Parse first A2UI block
  const firstMatch = a2uiMatches[0];
  const jsonMatch = firstMatch.match(/\{.*\}/);
  
  if (!jsonMatch) {
    return { a2ui: null, markdown: message };
  }
  
  try {
    const parsed = JSON.parse(jsonMatch[0]);
    const markdown = message.replace(A2UI_PATTERN, '').trim();
    
    return {
      a2ui: { type: parsed.type, props: parsed.props || {}, raw: firstMatch },
      markdown,
    };
  } catch {
    return { a2ui: null, markdown: message };
  }
}

export function isA2UIMessage(message: string): boolean {
  return A2UI_PATTERN.test(message);
}
