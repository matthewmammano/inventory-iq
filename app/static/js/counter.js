const counterValue = document.querySelector('.counter-value');
const counterInput = document.getElementById('counter_value');
const submitBtn = document.querySelector('.submit-btn');

// Handle all buttons with data-value (works for both guest and admin)
document.querySelectorAll('[data-value]').forEach(btn => {
    btn.addEventListener('click', function() {
        const changeValue = parseInt(this.dataset.value);
        let currentValue = parseInt(counterValue.textContent);
        let newValue = currentValue + changeValue;
        
        // Don't allow negative values
        if (newValue < 0) newValue = 0;
        
        counterValue.textContent = newValue;
        counterInput.value = newValue;
    });
});

submitBtn.addEventListener('click', function() {
    // Update the counter_value before submitting
    counterInput.value = counterValue.textContent;
    
    // Submit the form
    document.getElementById('hidden-form').submit();
});