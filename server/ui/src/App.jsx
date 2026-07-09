import DesktopApp from './DesktopApp.jsx';

// Theme now lives in <ThemeProvider> at the app root; the shell just renders
// the desktop layout.
function App() {
    return <DesktopApp />;
}

export default App;
