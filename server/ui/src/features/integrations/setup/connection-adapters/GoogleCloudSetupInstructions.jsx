import SetupInstructions, { ConsoleLink, SetupStep } from '../components/SetupInstructions.jsx';

export default function GoogleCloudSetupInstructions() {
    return (
        <SetupInstructions title="Google Cloud setup" testId="google-cloud-setup"
            description="This one-time setup creates the desktop OAuth client omnideck uses on this device.">
                <SetupStep number="1" title="Create a Google Cloud project">
                    <ConsoleLink href="https://console.cloud.google.com" host="console.cloud.google.com">
                        Open Google Cloud Console
                    </ConsoleLink>
                    <p>
                        Open the project picker at the top, choose <strong>New Project</strong>,
                        and give it a name you will recognize. The default project settings are fine.
                    </p>
                </SetupStep>

                <SetupStep number="2" title="Enable the Google APIs">
                    <ConsoleLink href="https://console.cloud.google.com/apis/library" host="console.cloud.google.com/apis/library">
                        Open the API Library
                    </ConsoleLink>
                    <p>Make sure your new project is selected, then search for and enable each API:</p>
                    <ul>
                        <li>Gmail API</li>
                        <li>Google Calendar API</li>
                        <li>Google Drive API</li>
                        <li>People API</li>
                    </ul>
                </SetupStep>

                <SetupStep number="3" title="Configure the Google Auth Platform">
                    <ConsoleLink href="https://console.cloud.google.com/auth/overview" host="console.cloud.google.com/auth">
                        Open Google Auth Platform
                    </ConsoleLink>
                    <p>
                        Choose <strong>Get started</strong> and complete the initial configuration:
                    </p>
                    <ul>
                        <li><strong>App information:</strong> use any app name and your email for user support.</li>
                        <li><strong>Audience:</strong> use External for personal Google accounts. Internal is only for accounts in the Google Workspace organization that owns the project.</li>
                        <li><strong>Contact information:</strong> enter your email.</li>
                        <li><strong>Finish:</strong> accept the Google API Services User Data Policy.</li>
                    </ul>
                </SetupStep>

                <SetupStep number="4" title="Choose the publishing status">
                    <ConsoleLink href="https://console.cloud.google.com/auth/audience" host="console.cloud.google.com/auth/audience">
                        Open Audience
                    </ConsoleLink>
                    <p>
                        For an External app you want to keep connected, choose
                        <strong> Publish app</strong> under Publishing status. In Testing,
                        Google authorizations expire after seven days for the scopes omnideck requests.
                    </p>
                    <p>
                        Publishing and verification are separate. Google may still show an
                        unverified-app warning because these APIs use sensitive scopes. Only
                        continue when the project and OAuth client are the ones you created.
                    </p>
                </SetupStep>

                <SetupStep number="5" title="Create a desktop OAuth client">
                    <ConsoleLink href="https://console.cloud.google.com/auth/clients" host="console.cloud.google.com/auth/clients">
                        Open OAuth clients
                    </ConsoleLink>
                    <p>
                        Choose <strong>Create client</strong>, set Application type to
                        <strong> Desktop app</strong>, and enter any name. Desktop app is required
                        because omnideck receives Google&rsquo;s response through a local loopback address.
                    </p>
                    <p>
                        Create the client, then copy its <strong>Client ID</strong> and
                        <strong> Client secret</strong> into the fields below. You can also find
                        both values in the downloaded client JSON.
                    </p>
                </SetupStep>
        </SetupInstructions>
    );
}
