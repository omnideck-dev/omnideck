import CodeBlock from '../../../../components/CodeBlock.jsx';
import SetupInstructions, { ConsoleLink, SetupStep } from '../components/SetupInstructions.jsx';

export default function SlackSetupInstructions({ manifest }) {
    return <SetupInstructions title="Set up your Slack app" testId="slack-app-setup"
        description="A workspace owner or app manager can do this once, then share the Client ID with teammates.">
        <SetupStep number="1" title="Create an internal app">
            <ConsoleLink href="https://api.slack.com/apps" host="api.slack.com/apps">Open Slack apps</ConsoleLink>
            <p>Choose <strong>Create New App → From a manifest</strong>, then select your workspace.
                Choose JSON, replace the example with the manifest below, review the permissions, and create the app.</p>
            <p>Keep this app internal to your organization. Do not enable public distribution.</p>
            <CodeBlock><code className="language-json">{JSON.stringify(manifest, null, 2)}</code></CodeBlock>
        </SetupStep>
        <SetupStep number="2" title="Check sign-in and workspace approval">
            <p>Under <strong>Agents</strong>, verify that <strong>Slack Model Context Protocol (MCP) Server</strong>
                is on. The manifest enables it for this app.</p>
            <p>Under <strong>OAuth &amp; Permissions</strong>, check that the redirect URL matches the one below and
                <strong> PKCE</strong> is enabled. The manifest sets up user permissions and token rotation;
                no bot token or client secret is needed.</p>
            <p>PKCE makes the app a public OAuth client; reversing that setting requires Slack support.
                Use a dedicated app rather than changing an existing bot.</p>
            <p>If your workspace requires app or MCP approval, ask an administrator to approve this internal app.
                Private-channel and direct-message search may also require consent inside Slack.</p>
        </SetupStep>
        <SetupStep number="3" title="Copy the Client ID and connect">
            <p>Open <strong>Basic Information → App Credentials</strong> and copy the <strong>Client ID</strong>
                into the field below. Do not copy the Client Secret or a token.</p>
            <p>Choose <strong>Connect</strong>, approve access in Slack, then return here to select tools.
                Teammates can reuse the Client ID, but each person signs in with their own Slack account.
                Add each installation’s redirect URL to the Slack app if its port differs.</p>
        </SetupStep>
    </SetupInstructions>;
}
