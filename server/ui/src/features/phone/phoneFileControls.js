import PhoneFileAction from './PhoneFileAction.jsx';

export const PHONE_FILE_CONTROLS = {
    card: {
        Actions: PhoneFileAction,
        open: ({ item, onPreview }) => onPreview?.(item),
    },
    preview: {
        Actions: PhoneFileAction,
    },
};
