import { stateConfig }       from '@/settings/state-config.js';
import { stateProviders }    from '@/settings/state-providers.js';
import { stateUI }           from '@/settings/state-ui.js';
import { browseDirState }    from '@/shared/state-browse-dir.js';
import { toastState }        from '@/shared/state-toast.js';
import { mergeState }        from '@/shared/merge-state.js';

document.addEventListener('alpine:init', () => {
    Alpine.data('settings', () => mergeState(
        stateConfig(),
        stateProviders(),
        stateUI(),
        browseDirState(),
        toastState(),
    ));
});
