import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TaskSidebar } from '../src/components/TaskSidebar';
import { Notifications } from '../src/components/Notifications';
import '../src/style.css';
import.meta.glob('../src/**/*.css', { eager: true });

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><Notifications>
  <div className="workspace-with-tasks"><TaskSidebar /><main><h1>侧栏隔离测试</h1><button>正文外部操作</button></main>
    <footer className="site-footer"><button>侧栏外部操作</button></footer>
  </div>
</Notifications></QueryClientProvider>);
