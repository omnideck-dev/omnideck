import React, { Suspense, lazy } from 'react';
import ReactDOM from 'react-dom/client';
import { ToastProvider } from './components/ToastProvider.jsx';
import { AppDataProvider } from './contexts/AppData.jsx';
import { ThemeProvider } from './contexts/Theme.jsx';
import { csrfFetch } from './utils/csrfFetch.js';
import { isPhoneDevice } from './features/phone/phoneDevice.js';
import 'bootstrap-icons/font/bootstrap-icons.css';
import './global.css';
import './hljs-tokens.css';

// Appended (not imported) so it lands after the bundled core styles in the
// document — later <link> tags win the cascade on equal specificity, letting
// user overrides in custom.css take effect without touching core CSS.
const customStylesLink = document.createElement('link');
customStylesLink.rel = 'stylesheet';
customStylesLink.href = '/custom.css';
document.head.appendChild(customStylesLink);

// Patch fetch so mutating application requests carry the CSRF header.
// The server requires X-Requested-With: XMLHttpRequest on POST/PUT/DELETE.
// Same-origin JS can set this freely; cross-origin JS cannot because the
// server does not list it in Access-Control-Allow-Headers. Leave non-app
// requests untouched so native WebView protocols retain their own headers.
const _originalFetch = window.fetch;
window.fetch = csrfFetch(_originalFetch);

const Root = isPhoneDevice()
    ? lazy(() => import('./features/phone/PhoneApp.jsx'))
    : lazy(() => import('./App.jsx'));

ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
        <ThemeProvider>
            <ToastProvider>
                <AppDataProvider>
                    <Suspense fallback={null}>
                        <Root />
                    </Suspense>
                </AppDataProvider>
            </ToastProvider>
        </ThemeProvider>
    </React.StrictMode>
);
