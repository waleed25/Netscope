import { ReactNode, createContext, useContext } from 'react';
import { A2UI_COMPONENT_REGISTRY, A2UIComponentName } from './registry';

interface A2UIContextValue {
  components: typeof A2UI_COMPONENT_REGISTRY;
  registerComponent: (name: string, component: any) => void;
  isRegistered: (name: string) => boolean;
}

const A2UIContext = createContext<A2UIContextValue | null>(null);

interface A2UIProviderProps {
  children: ReactNode;
}

export function A2UIProvider({ children }: A2UIProviderProps) {
  const value: A2UIContextValue = {
    components: A2UI_COMPONENT_REGISTRY,
    registerComponent: (name: string, component: any) => {
      // Future: dynamic registration
      console.log(`Registered component: ${name}`);
    },
    isRegistered: (name: string): boolean => {
      return name in A2UI_COMPONENT_REGISTRY;
    },
  };

  return (
    <A2UIContext.Provider value={value}>
      {children}
    </A2UIContext.Provider>
  );
}

export function useA2UI(): A2UIContextValue {
  const context = useContext(A2UIContext);
  if (!context) {
    throw new Error('useA2UI must be used within A2UIProvider');
  }
  return context;
}

export type { A2UIComponentName };
