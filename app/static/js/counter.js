const counterValue = document.querySelector('.counter-value');
const counterInput = document.getElementById('counter_value');
const submitBtn = document.querySelector('.submit-btn');
const hiddenForm = document.getElementById('hidden-form');
const minValue = parseInt(counterInput?.dataset.minValue || '0');

// Handle all buttons with data-value (works for both guest and admin)
document.querySelectorAll('[data-value]').forEach(btn => {
    btn.addEventListener('click', function() {
        if (this.dataset.value === 'reset') {
            counterValue.textContent = 1;
            counterInput.value = 1;
            return;
        }
        const changeValue = parseInt(this.dataset.value);
        let currentValue = parseInt(counterValue.textContent);
        let newValue = currentValue + changeValue;

        if (newValue < minValue) newValue = minValue;

        counterValue.textContent = newValue;
        counterInput.value = newValue;
    });
});

submitBtn.addEventListener('click', function() {
    counterInput.value = counterValue.textContent;

    if (!hiddenForm) return;
    if (typeof hiddenForm.requestSubmit === 'function') {
        hiddenForm.requestSubmit();
        return;
    }
    hiddenForm.submit();
});
