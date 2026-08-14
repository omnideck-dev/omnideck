import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import { ToastProvider } from './components/ToastProvider.jsx';
import { AppDataProvider } from './contexts/AppData.jsx';
import { ThemeProvider } from './contexts/Theme.jsx';
import { csrfFetch } from './utils/csrfFetch.js';
import 'bootstrap-icons/font/bootstrap-icons.css';
import './global.css';
import './hljs-tokens.css';

// Patch fetch so mutating application requests carry the CSRF header.
// The server requires X-Requested-With: XMLHttpRequest on POST/PUT/DELETE.
// Same-origin JS can set this freely; cross-origin JS cannot because the
// server does not list it in Access-Control-Allow-Headers. Leave non-app
// requests untouched so native WebView protocols retain their own headers.
const _originalFetch = window.fetch;
window.fetch = csrfFetch(_originalFetch);

ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
        <ThemeProvider>
            <ToastProvider>
                <AppDataProvider>
                    <App />
                </AppDataProvider>
            </ToastProvider>
        </ThemeProvider>
    </React.StrictMode>
);
