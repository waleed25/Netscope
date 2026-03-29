import { useA2UI } from './A2UIProvider';
import { ParsedA2UI } from '../../lib/a2ui/parser';

interface A2UIRendererProps {
  a2ui: ParsedA2UI | null;
}

export function A2UIRenderer({ a2ui }: A2UIRendererProps) {
  const { components } = useA2UI();
  
  if (!a2ui) return null;
  
  const componentDef = components[a2ui.type as keyof typeof components];
  
  if (!componentDef) {
    console.warn(`A2UI component "${a2ui.type}" not found in registry`);
    return (
      <div className="p-4 bg-yellow-900/50 border border-yellow-700 rounded-lg text-yellow-200">
        Component "{a2ui.type}" not available
      </div>
    );
  }
  
  const Component = componentDef.component;
  
  // Merge default props with provided props
  const props = {
    ...componentDef.defaultProps,
    ...a2ui.props,
  };
  
  return (
    <div className="a2ui-renderer my-4">
      <Component {...props} />
    </div>
  );
}
