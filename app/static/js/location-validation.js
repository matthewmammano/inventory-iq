document.addEventListener('DOMContentLoaded', function() {
    const fromRadios = document.querySelectorAll('input[name="from_location_id"]');
    const toRadios = document.querySelectorAll('input[name="to_location_id"]');
    const toOptions = document.querySelectorAll('#to-location-options .location-option');
    const form = document.getElementById('scan-form');
    const sameLocationErrorInput = document.getElementById('same_location_error');

    function highlightIfSame() {
        let fromVal = document.querySelector('input[name="from_location_id"]:checked');
        let toVal = document.querySelector('input[name="to_location_id"]:checked');
        // Remove previous highlights
        toOptions.forEach(opt => opt.classList.remove('location-error'));
        if (fromVal && toVal && fromVal.value === toVal.value) {
            // Highlight the selected "to" option
            let toRadio = document.querySelector('input[name="to_location_id"]:checked');
            if (toRadio) {
                toRadio.closest('.location-option').classList.add('location-error');
            }
        }
    }

    function checkSameLocationError() {
        let fromVal = document.querySelector('input[name="from_location_id"]:checked');
        let toVal = document.querySelector('input[name="to_location_id"]:checked');
        if (fromVal && toVal && fromVal.value === toVal.value) {
            sameLocationErrorInput.value = "1";
        } else {
            sameLocationErrorInput.value = "0";
        }
    }

    fromRadios.forEach(radio => {
        radio.addEventListener('change', highlightIfSame);
        radio.addEventListener('change', checkSameLocationError);
    });
    toRadios.forEach(radio => {
        radio.addEventListener('change', highlightIfSame);
        radio.addEventListener('change', checkSameLocationError);
    });

    form.addEventListener('submit', function(e) {
        checkSameLocationError();
        // If error, allow form to submit so server can handle
    });
});