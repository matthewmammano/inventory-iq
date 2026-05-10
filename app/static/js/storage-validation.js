document.addEventListener('DOMContentLoaded', function() {
    const fromRadios = document.querySelectorAll('input[name="from_location_id"]');
    const toRadios = document.querySelectorAll('input[name="to_location_id"]');
    const toOptions = document.querySelectorAll('#to-storage-options .storage-option');
    const form = document.getElementById('scan-form');
    const sameStorageErrorInput = document.getElementById('same_location_error');

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
        toOptions.forEach(opt => opt.classList.remove('storage-error'));
        sameStorageErrorInput.value = hasInvalidCombination() ? '1' : '0';
        if (sameStorageErrorInput.value !== '1') {
            return;
        }
        const toRadio = selectedValue('to_location_id');
        if (toRadio) {
            toRadio.closest('.storage-option').classList.add('storage-error');
        }
    }

    fromRadios.forEach(radio => radio.addEventListener('change', updateInvalidState));
    toRadios.forEach(radio => radio.addEventListener('change', updateInvalidState));
    form.addEventListener('submit', updateInvalidState);
});
