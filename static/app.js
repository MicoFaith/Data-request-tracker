/* Progressive enhancement: server validation and ordinary forms remain authoritative. */
(() => {
    const busy = (form, value) => {
        if (!form) return;
        form.querySelectorAll('button[type="submit"], button:not([type])').forEach(button => {
            if (value && !button.disabled) {
                button.dataset.busy = 'true';
                button.disabled = true;
            } else if (!value && button.dataset.busy) {
                button.disabled = false;
                delete button.dataset.busy;
            }
        });
        form.setAttribute('aria-busy', String(value));
    };
    const prepare = () => {
        document.querySelectorAll('[data-password-toggle]').forEach(button => {
            button.hidden = false;
        });
        document.querySelectorAll('textarea[maxlength]').forEach(field => {
            if (field.dataset.counterReady) return;
            field.dataset.counterReady = 'true';
            const counter = document.createElement('span');
            counter.className = 'character-count';
            const update = () => {
                counter.textContent = `${field.value.length.toLocaleString()} / ${field.maxLength.toLocaleString()} characters`;
            };
            field.after(counter);
            field.addEventListener('input', update);
            update();
        });
        document.querySelectorAll('input[type="file"]').forEach(field => {
            if (field.dataset.sizeReady) return;
            field.dataset.sizeReady = 'true';
            field.addEventListener('change', () => {
                const tooLarge = field.files[0] && field.files[0].size > 10 * 1024 * 1024;
                field.setCustomValidity(tooLarge ? 'Choose a CSV file of 10 MiB or less.' : '');
                if (tooLarge) field.reportValidity();
            });
        });
    };
    document.addEventListener('click', event => {
        const button = event.target.closest('[data-password-toggle]');
        if (button) {
            const input = document.getElementById(button.dataset.passwordToggle);
            const show = input.type === 'password';
            input.type = show ? 'text' : 'password';
            button.textContent = show ? 'Hide' : 'Show';
            button.setAttribute('aria-pressed', String(show));
        }
        if (event.target.closest('[data-reload]')) window.location.reload();
    });
    document.addEventListener('submit', event => {
        const form = event.target;
        // Native forms need no HTMX dependency, and disable only after submission is captured.
        if (form.matches('[hx-boost="false"], [data-busy-form]') && form.getAttribute('hx-boost') === 'false') {
            setTimeout(() => busy(form, true), 0);
        }
    });
    document.addEventListener('htmx:beforeRequest', event => {
        document.getElementById('connection-error').hidden = true;
        busy(event.detail.elt.closest('form'), true);
    });
    document.addEventListener('htmx:afterRequest', event => busy(event.detail.elt.closest('form'), false));
    document.addEventListener('htmx:afterSwap', event => {
        if (event.detail.target.id !== 'content') return;
        prepare();
        const target = document.getElementById('validation-summary') || document.querySelector('#content h1');
        if (target) {
            target.setAttribute('tabindex', '-1');
            target.focus({
                preventScroll: true
            });
        }
        if (window.location.hash) {
            const anchor = document.getElementById(window.location.hash.slice(1));
            if (anchor) anchor.scrollIntoView();
        }
    });
    ['htmx:sendError', 'htmx:timeout'].forEach(name => document.addEventListener(name, () => {
        document.getElementById('connection-error').hidden = false;
    }));
    window.addEventListener('pageshow', () => document.querySelectorAll('form').forEach(form => busy(form, false)));
    document.addEventListener('DOMContentLoaded', prepare);
})();
