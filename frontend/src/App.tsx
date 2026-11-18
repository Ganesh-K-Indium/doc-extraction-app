import { Route, Routes } from 'react-router-dom';
import Landing from './pages/Landing';
import Shell from './components/Shell';
import WorkspaceLayout from './components/WorkspaceLayout';
import WorkspacesPage from './pages/WorkspacesPage';
import ListPage from './pages/ListPage';
import ExtractionPage from './pages/ExtractionPage';
import TypesPage from './pages/TypesPage';

export default function App() {
    return (
        <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/app" element={<Shell />}>
                <Route index element={<WorkspacesPage />} />
                <Route path="w/:wid" element={<WorkspaceLayout />}>
                    <Route index element={<ListPage />} />
                    <Route path="e/:id" element={<ExtractionPage />} />
                    <Route path="types" element={<TypesPage />} />
                </Route>
            </Route>
        </Routes>
    );
}
