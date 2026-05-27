document.addEventListener('DOMContentLoaded', function() {
    const fromRadios = document.querySelectorAll('input[name="from_location_id"]');
    const toRadios = document.querySelectorAll('input[name="to_location_id"]');
    const allChoices = document.querySelectorAll('.choice');
    const form = document.getElementById('scan-form');
    const sameStorageErrorInput = document.getElementById('same_location_error');
    const routeStatus = document.getElementById('route-status');
    const routeLabel = document.getElementById('route-label');
    const continuePanel = document.getElementById('continue-panel');
    const continueButton = document.getElementById('continue-button');

    function selectedValue(name) {
        return document.querySelector(`input[name="${name}"]:checked`);
    }

    function hasInvalidCombination() {
        const fromVal = selectedValue('from_location_id');
        const toVal = selectedValue('to_location_id');
        if (!fromVal || !toVal) {
            return false;
        }
        return (
            fromVal.value === toVal.value ||
            (fromVal.value === '-2' && toVal.value === '-1') ||
            (fromVal.value === '-1' && toVal.value === '-1')
        );
    }

    function updateInvalidState() {
        allChoices.forEach(choice => choice.classList.remove('invalid'));
        const fromRadio = selectedValue('from_location_id');
        const toRadio = selectedValue('to_location_id');
        const invalid = hasInvalidCombination();
        sameStorageErrorInput.value = invalid ? '1' : '0';
        if (fromRadio && toRadio && routeLabel) {
            routeLabel.textContent = `${fromRadio.closest('.radio-card').textContent.trim()} -> ${toRadio.closest('.radio-card').textContent.trim()}`;
        }
        if (routeStatus) {
            routeStatus.textContent = invalid ? 'Invalid storage selection' : (fromRadio && toRadio ? 'Ready to continue' : 'Choose storages');
        }
        if (continuePanel) continuePanel.classList.toggle('invalid', invalid);
        if (continueButton) continueButton.disabled = invalid;
        if (invalid) {
            fromRadio?.closest('.radio-card')?.querySelector('.choice')?.classList.add('invalid');
            toRadio?.closest('.radio-card')?.querySelector('.choice')?.classList.add('invalid');
        }
    }

    fromRadios.forEach(radio => radio.addEventListener('change', updateInvalidState));
    toRadios.forEach(radio => radio.addEventListener('change', updateInvalidState));
    form.addEventListener('submit', updateInvalidState);
    updateInvalidState();
});
