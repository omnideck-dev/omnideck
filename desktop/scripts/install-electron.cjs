// Puts the Electron binary in place before the smoke suite runs.
//
// Requiring electron downloads the binary on demand rather than at install
// time, and the test runner starts one process per file. Left to the suite,
// several of those processes ask for the binary at once and write over each
// other: the launches that follow get a half-written executable, which fails
// as a refusal to start rather than as anything to do with the application.
//
// Doing it once, in one process, is enough — the download is skipped when the
// binary is already there.
require('electron');
