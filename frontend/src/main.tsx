import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import '@fontsource-variable/instrument-sans';
import App from './App';
import { applyTheme, getTheme } from './lib/theme';
import './theme.css';
import './index.css';

applyTheme(getTheme());          // also keeps the browser's own chrome in step with the canvas

createRoot(document.getElementById('root')!).render(
    <StrictMode><BrowserRouter><App /></BrowserRouter></StrictMode>,
);
