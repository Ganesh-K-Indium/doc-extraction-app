import { Route, Routes } from 'react-router-dom';
import Landing from './pages/Landing';
import Shell from './components/Shell';
import ListPage from './pages/ListPage';
import ExtractionPage from './pages/ExtractionPage';
import TypesPage from './pages/TypesPage';

export default function App() {
    return (
        <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/app" element={<Shell />}>
                <Route index element={<ListPage />} />
                <Route path="e/:id" element={<ExtractionPage />} />
                <Route path="types" element={<TypesPage />} />
            </Route>
        </Routes>
    );
}
