const minusBtn = document.querySelector('.minus-btn');
const plusBtn = document.querySelector('.plus-btn');
const counterValue = document.querySelector('.counter-value');
const counterInput = document.getElementById('counter_value');
const submitBtn = document.querySelector('.submit-btn');

minusBtn.addEventListener('click', function() {
    let value = parseInt(counterValue.textContent);
    if (value > 0) {
        value = value - 1;
        counterValue.textContent = value;
        counterInput.value = value;
    }
});

plusBtn.addEventListener('click', function() {
    let value = parseInt(counterValue.textContent);
    value = value + 1;
    counterValue.textContent = value;
    counterInput.value = value;
});

submitBtn.addEventListener('click', function() {
    // Update the counter_value before submitting
    counterInput.value = counterValue.textContent;
    
    // Submit the form
    document.getElementById('hidden-form').submit();
});