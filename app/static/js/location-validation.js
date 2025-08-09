document.addEventListener('DOMContentLoaded', function() {
    const fromRadios = document.querySelectorAll('input[name="from_location_id"]');
    const toRadios = document.querySelectorAll('input[name="to_location_id"]');
    const toOptions = document.querySelectorAll('#to-location-options .location-option');
    const form = document.getElementById('scan-form');
    const sameLocationErrorInput = document.getElementById('same_location_error');

    function highlightIfInvalid() {
        let fromVal = document.querySelector('input[name="from_location_id"]:checked');
        let toVal = document.querySelector('input[name="to_location_id"]:checked');
        // Remove previous highlights
        toOptions.forEach(opt => opt.classList.remove('location-error'));
        
        if (fromVal && toVal) {
            // Check for invalid combinations
            let isInvalid = false;
            
            // Same location error
            if (fromVal.value === toVal.value) {
                isInvalid = true;
            }
            // COUNT (-2) -> TAKE (-1) is invalid
            else if (fromVal.value === "-2" && toVal.value === "-1") {
                isInvalid = true;
            }
            // RESTOCK (-1) -> TAKE (-1) is invalid  
            else if (fromVal.value === "-1" && toVal.value === "-1") {
                isInvalid = true;
            }
            
            if (isInvalid) {
                // Highlight the selected "to" option
                let toRadio = document.querySelector('input[name="to_location_id"]:checked');
                if (toRadio) {
                    toRadio.closest('.location-option').classList.add('location-error');
                }
            }
        }
    }

    function checkInvalidCombination() {
        let fromVal = document.querySelector('input[name="from_location_id"]:checked');
        let toVal = document.querySelector('input[name="to_location_id"]:checked');
        
        let hasError = false;
        
        if (fromVal && toVal) {
            // Same location error
            if (fromVal.value === toVal.value) {
                hasError = true;
            }
            // COUNT (-2) -> TAKE (-1) is invalid
            else if (fromVal.value === "-2" && toVal.value === "-1") {
                hasError = true;
            }
            // RESTOCK (-1) -> TAKE (-1) is invalid
            else if (fromVal.value === "-1" && toVal.value === "-1") {
                hasError = true;
            }
        }
        
        sameLocationErrorInput.value = hasError ? "1" : "0";
    }

    fromRadios.forEach(radio => {
        radio.addEventListener('change', highlightIfInvalid);
        radio.addEventListener('change', checkInvalidCombination);
    });
    toRadios.forEach(radio => {
        radio.addEventListener('change', highlightIfInvalid);
        radio.addEventListener('change', checkInvalidCombination);
    });

    form.addEventListener('submit', function(e) {
        checkInvalidCombination();
        // If error, allow form to submit so server can handle the error message
    });
});