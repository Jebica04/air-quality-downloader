// Air Quality Data Downloader - JavaScript
// Global variables
let currentDeviceData = null;
let testInProgress = false;

// Show/hide time inputs based on data type selection
document.querySelectorAll('input[name="data_type"]').forEach(radio => {
    radio.addEventListener('change', function() {
        const timeInputs = document.getElementById('timeInputs');
        if (this.value === 'time_range') {
            timeInputs.classList.add('show');
        } else {
            timeInputs.classList.remove('show');
        }
    });
});

// Alert system
function showAlert(message, type = 'error') {
    const alertsContainer = document.getElementById('alerts');
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type}`;
    alertDiv.innerHTML = `
        <strong>${type === 'error' ? '❌' : type === 'success' ? '✅' : type === 'warning' ? '⚠️' : 'ℹ️'}</strong>
        ${message}
    `;
    alertsContainer.innerHTML = '';
    alertsContainer.appendChild(alertDiv);
    
    // Auto-dismiss after 5 seconds for success/info alerts
    if (type === 'success' || type === 'info') {
        setTimeout(() => {
            if (alertDiv.parentNode) {
                alertDiv.remove();
            }
        }, 5000);
    }

    // Scroll to alert
    alertDiv.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function clearAlerts() {
    document.getElementById('alerts').innerHTML = '';
}

// Loading system
function showLoading(show, message = 'Processing your request...') {
    const loading = document.getElementById('loading');
    const spinnerText = loading.querySelector('.spinner-text');
    spinnerText.textContent = message;
    loading.classList.toggle('show', show);
}

// Progress bar
function showProgress(show, percentage = 0) {
    const progressBar = document.getElementById('test_progress');
    const progressFill = progressBar.querySelector('.progress-fill');
    
    if (show) {
        progressBar.style.display = 'block';
        progressFill.style.width = percentage + '%';
    } else {
        progressBar.style.display = 'none';
        progressFill.style.width = '0%';
    }
}

// Form validation
function validateForm() {
    const deviceMac = document.getElementById('device_mac').value;
    const dataType = document.querySelector('input[name="data_type"]:checked').value;
    
    if (!deviceMac) {
        showAlert('Please select a device or add a new one first', 'warning');
        return false;
    }
    
    if (dataType === 'time_range') {
        const startDate = document.getElementById('start_date').value;
        const endDate = document.getElementById('end_date').value;
        const hoursFrom = document.getElementById('hours_from').value;
        const hoursTo = document.getElementById('hours_to').value;
        
        if (!startDate || !endDate) {
            showAlert('Please select both start and end dates for time range data', 'warning');
            return false;
        }
        
        if (!hoursFrom || !hoursTo) {
            showAlert('Please enter both start and end hours for time range data', 'warning');
            return false;
        }
        
        const start = new Date(startDate);
        const end = new Date(endDate);
        
        if (start > end) {
            showAlert('Start date must be before or equal to end date', 'warning');
            return false;
        }
        
        const from = parseInt(hoursFrom);
        const to = parseInt(hoursTo);
        
        if (from < 0 || from > 23 || to < 0 || to > 23) {
            showAlert('Hours must be between 0 and 23', 'warning');
            return false;
        }
        
        if (from >= to) {
            showAlert('Start hour must be less than end hour', 'warning');
            return false;
        }
    }
    
    return true;
}

// Device selection handling
document.getElementById('device_mac').addEventListener('change', function() {
    const removeBtn = document.getElementById('remove_device_btn');
    const deviceStatus = document.getElementById('device_status');
    
    removeBtn.disabled = !this.value;
    
    if (this.value) {
        const selectedOption = this.options[this.selectedIndex];
        deviceStatus.textContent = `📱 Selected: ${selectedOption.text}`;
        deviceStatus.className = 'device-status online';
    } else {
        deviceStatus.textContent = 'No device selected';
        deviceStatus.className = 'device-status offline';
    }
});

// MAC address input formatting
document.getElementById('new_mac').addEventListener('input', function() {
    let value = this.value.replace(/[^a-fA-F0-9]/g, '');
    if (value.length > 12) value = value.substring(0, 12);
    
    // Add colons every 2 characters
    value = value.replace(/(.{2})(?=.)/g, '$1:');
    this.value = value;
});

// Test device functionality
document.getElementById('test_device_btn').addEventListener('click', async function() {
    if (testInProgress) return;
    
    const mac = document.getElementById('new_mac').value.trim();
    const testResult = document.getElementById('test_result');
    const saveBtn = document.getElementById('save_device_btn');
    
    if (!mac) {
        showAlert('Please enter a MAC address', 'warning');
        return;
    }
    
    const macPattern = /^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$/;
    if (!macPattern.test(mac)) {
        showAlert('Invalid MAC address format. Use format: aa:bb:cc:dd:ee:ff', 'warning');
        return;
    }
    
    testInProgress = true;
    this.disabled = true;
    this.textContent = '🔄 Testing...';
    testResult.innerHTML = '<span style="color: #666;">🔍 Testing device connection...</span>';
    saveBtn.disabled = true;
    
    showProgress(true, 25);
    
    try {
        const formData = new FormData();
        formData.append('mac', mac);
        
        showProgress(true, 50);
        
        const response = await fetch('/api/devices/test', {
            method: 'POST',
            body: formData
        });
        
        showProgress(true, 75);
        
        const result = await response.json();
        
        showProgress(true, 100);
        
        if (result.works) {
            testResult.innerHTML = `<span style="color: #28a745;">✅ Device online: ${result.message}</span>`;
            saveBtn.disabled = false;
            showAlert('Device test successful! You can now save this device.', 'success');
        } else {
            testResult.innerHTML = `<span style="color: #dc3545;">❌ Device offline: ${result.message}</span>`;
            saveBtn.disabled = true;
            showAlert(`Device test failed: ${result.message}`, 'error');
        }
    } catch (error) {
        testResult.innerHTML = '<span style="color: #dc3545;">❌ Network error - please try again</span>';
        saveBtn.disabled = true;
        showAlert('Network error during device test. Please check your connection and try again.', 'error');
    } finally {
        testInProgress = false;
        this.disabled = false;
        this.textContent = '🧪 Test';
        setTimeout(() => showProgress(false), 1000);
    }
});

// Save device functionality
document.getElementById('save_device_btn').addEventListener('click', async function() {
    const mac = document.getElementById('new_mac').value.trim();
    const name = document.getElementById('new_name').value.trim();
    
    this.disabled = true;
    this.textContent = '💾 Saving...';
    
    try {
        const formData = new FormData();
        formData.append('mac', mac);
        if (name) formData.append('name', name);
        
        const response = await fetch('/api/devices/save', {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (result.success) {
            showAlert('Device saved successfully! It\'s now available in your device list.', 'success');
            document.getElementById('new_mac').value = '';
            document.getElementById('new_name').value = '';
            document.getElementById('test_result').innerHTML = '';
            this.disabled = true;
            loadSavedDevices();
        } else {
            showAlert(result.error || 'Failed to save device', 'error');
        }
    } catch (error) {
        showAlert('Network error while saving device', 'error');
    } finally {
        this.textContent = '💾 Save';
    }
});

// Remove device functionality
document.getElementById('remove_device_btn').addEventListener('click', async function() {
    const deviceSelect = document.getElementById('device_mac');
    const mac = deviceSelect.value;
    const deviceName = deviceSelect.options[deviceSelect.selectedIndex].text;
    
    if (!mac || !confirm(`Are you sure you want to remove device "${deviceName}"?`)) {
        return;
    }
    
    this.disabled = true;
    this.textContent = '🗑️ Removing...';
    
    try {
        const formData = new FormData();
        formData.append('mac', mac);
        
        const response = await fetch('/api/devices/remove', {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (result.success) {
            showAlert('Device removed successfully', 'success');
            loadSavedDevices();
        } else {
            showAlert(result.error || 'Failed to remove device', 'error');
        }
    } catch (error) {
        showAlert('Network error while removing device', 'error');
    } finally {
        this.textContent = '🗑️ Remove Selected';
    }
});

// Load saved devices
async function loadSavedDevices() {
    const deviceSelect = document.getElementById('device_mac');
    const deviceStatus = document.getElementById('device_status');
    
    try {
        const response = await fetch('/api/devices');
        const devices = await response.json();
        
        deviceSelect.innerHTML = '<option value="">Choose a device...</option>';
        
        if (devices.length > 0) {
            devices.forEach(device => {
                const option = document.createElement('option');
                option.value = device.mac;
                option.textContent = `${device.name} (${device.mac})`;
                deviceSelect.appendChild(option);
            });
            
            deviceStatus.textContent = `📱 ${devices.length} saved device${devices.length === 1 ? '' : 's'} available`;
            deviceStatus.className = 'device-status online';
        } else {
            deviceSelect.innerHTML = '<option value="">No saved devices yet</option>';
            deviceStatus.textContent = '📝 No devices saved. Add your first device above!';
            deviceStatus.className = 'device-status offline';
            showAlert('No saved devices found. Enter a MAC address above to get started.', 'info');
        }
        
        document.getElementById('remove_device_btn').disabled = true;
    } catch (error) {
        deviceSelect.innerHTML = '<option value="">Error loading devices</option>';
        deviceStatus.textContent = '❌ Error loading devices';
        deviceStatus.className = 'device-status offline';
        showAlert('Error loading saved devices. Please refresh the page.', 'error');
    }
}

// Enhanced field display name mapping
function getFieldDisplayName(key) {
    const fieldMappings = {
        'mac': 'Device MAC',
        'timestamp': 'Timestamp',
        'date': 'Date',
        'time': 'Time',
        'location': 'Location',
        'lat': 'Latitude', 
        'latitude': 'Latitude',
        'lng': 'Longitude', 
        'longitude': 'Longitude',
        'alt': 'Altitude',
        'iaq': 'IAQ Index', 
        'aqi': 'AQI',
        'calculatedAqi': 'Calculated AQI', 
        'dustAqi': 'Dust AQI',
        'dustAqiLevel': 'Dust Level', 
        'trafficAqi': 'Traffic AQI',
        'trafficAqiLevel': 'Traffic Level', 
        'industrialAqi': 'Industrial AQI',
        'industrialAqiLevel': 'Industrial Level', 
        'airQualityLevel': 'Air Quality',
        'aqi_level': 'AQI Level',
        't': 'Temperature (°C)', 
        'pm25': 'PM2.5 (μg/m³)', 
        'pm10': 'PM10 (μg/m³)',
        'co': 'CO (ppm)', 
        'no2': 'NO₂ (ppb)', 
        'so2': 'SO₂ (ppb)', 
        'o3': 'O₃ (ppb)',
        'battery': 'Battery (%)',
        'data_source': 'Data Source'
    };
    
    return fieldMappings[key] || key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

// Enhanced cell value formatting
function formatCellValue(key, value) {
    if (key === 'timestamp' && value) {
        return new Date(value).toLocaleString();
    } else if ((key === 'lat' || key === 'lng' || key === 'latitude' || key === 'longitude') && value !== null && value !== undefined) {
        return parseFloat(value).toFixed(6);
    } else if ((key === 't' || key.includes('Aqi') || key === 'aqi' || key === 'iaq') && value !== null && !isNaN(value)) {
        return parseFloat(value).toFixed(1);
    } else if (key === 'battery' && value !== null && !isNaN(value)) {
        return `${value}%`;
    } else if (key === 'location' && value && typeof value === 'string' && value.length > 40) {
        return value.substring(0, 40) + '...';
    } else if (typeof value === 'object' && value !== null) {
        return JSON.stringify(value);
    } else if (typeof value === 'string' && value.length > 30 && key !== 'location') {
        return value.substring(0, 30) + '...';
    } else if (value === null || value === undefined) {
        return '—';
    }
    return value;
}

// Enhanced data preview table creation
function createPreviewTable(data) {
    if (!data || data.length === 0) {
        return '<div style="text-align: center; padding: 40px; color: #666;">📊 No data available</div>';
    }
    
    const sample = data[0];
    
    // Priority fields for display with location
    const priorityFields = [
        'mac', 'timestamp', 'date', 'time', 'location', 'latitude', 'longitude', 'alt', 
        'airQualityLevel', 'iaq', 'calculatedAqi', 'aqi', 'aqi_level', 'dustAqi', 'dustAqiLevel',
        'trafficAqi', 'trafficAqiLevel', 'industrialAqi', 'industrialAqiLevel',
        't', 'pm25', 'pm10', 'co', 'no2', 'so2', 'o3', 'battery', 'data_source'
    ];
    
    const availableKeys = Object.keys(sample);
    const selectedKeys = [];
    
    // Add priority fields that exist
    priorityFields.forEach(field => {
        if (availableKeys.includes(field) && selectedKeys.length < 12) {
            selectedKeys.push(field);
        }
    });
    
    // Fill remaining slots with other fields
    availableKeys.forEach(field => {
        if (!selectedKeys.includes(field) && selectedKeys.length < 12) {
            selectedKeys.push(field);
        }
    });
    
    let html = '<div style="overflow-x: auto;"><table class="preview-table"><thead><tr>';
    
    selectedKeys.forEach(key => {
        let displayName = getFieldDisplayName(key);
        html += `<th>${displayName}</th>`;
    });
    html += '</tr></thead><tbody>';
    
    data.forEach(row => {
        html += '<tr>';
        selectedKeys.forEach(key => {
            let value = formatCellValue(key, row[key]);
            
            // Apply colors for AQI levels
            let cellStyle = '';
            if (key.toLowerCase().includes('level') || key === 'airQualityLevel' || key === 'aqi_level') {
                cellStyle = getAqiColor(row[key]);
            }
            
            html += `<td style="${cellStyle}" title="${row[key]}">${value}</td>`;
        });
        html += '</tr>';
    });
    
    html += '</tbody></table></div>';
    return html;
}

// AQI color coding
function getAqiColor(level) {
    if (!level) return '';
    
    const levelStr = level.toString().toLowerCase();
    
    if (levelStr.includes('good') || levelStr.includes('excellent')) {
        return 'background-color: #e8f5e8; color: #2e7d32;';
    } else if (levelStr.includes('moderate') || levelStr.includes('fair')) {
        return 'background-color: #fff3e0; color: #ef6c00;';
    } else if (levelStr.includes('unhealthy') || levelStr.includes('poor')) {
        return 'background-color: #ffebee; color: #c62828;';
    } else if (levelStr.includes('hazardous') || levelStr.includes('dangerous')) {
        return 'background-color: #4a0e4e; color: white;';
    } else if (levelStr.includes('very')) {
        return 'background-color: #ffcdd2; color: #b71c1c;';
    }
    
    return '';
}

// Preview data functionality
document.getElementById('previewBtn').addEventListener('click', async function() {
    if (!validateForm()) return;
    
    clearAlerts();
    showLoading(true, 'Loading data preview...');
    
    const formData = new FormData(document.getElementById('dataForm'));
    
    try {
        const response = await fetch('/preview_data', {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        if (result.success) {
            const previewSection = document.getElementById('previewSection');
            const previewContent = document.getElementById('previewContent');
            const recordCount = document.getElementById('recordCount');
            
            currentDeviceData = result.data;
            recordCount.textContent = `📊 Showing ${result.data.length} of ${result.total_records} records`;
            previewContent.innerHTML = createPreviewTable(result.data);
            previewSection.classList.add('show');
            
            // Scroll to preview
            previewSection.scrollIntoView({ behavior: 'smooth' });
            
            showAlert('Data preview loaded successfully! Review the data below.', 'success');
        } else {
            showAlert(result.error || 'Failed to load data preview', 'error');
        }
    } catch (error) {
        showAlert('Network error occurred while loading preview', 'error');
    } finally {
        showLoading(false);
    }
});

// Close preview functionality
document.getElementById('closePreviewBtn').addEventListener('click', function() {
    document.getElementById('previewSection').classList.remove('show');
    currentDeviceData = null;
});

// Download data functionality
document.getElementById('downloadBtn').addEventListener('click', async function() {
    if (!validateForm()) return;
    
    clearAlerts();
    showLoading(true, 'Preparing download...');
    
    const formData = new FormData(document.getElementById('dataForm'));
    
    try {
        const response = await fetch('/download_data', {
            method: 'POST',
            body: formData
        });
        
        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            
            // Get filename from response headers or use default
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = 'air_quality_data.csv';
            if (contentDisposition) {
                const match = contentDisposition.match(/filename="(.+)"/);
                if (match) filename = match[1];
            }
            
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            
            showAlert('✅ File downloaded successfully! Check your downloads folder.', 'success');
        } else {
            const error = await response.json();
            showAlert(error.error || 'Failed to download data', 'error');
        }
    } catch (error) {
        showAlert('Network error occurred during download', 'error');
    } finally {
        showLoading(false);
    }
});

// Initialize application
window.addEventListener('load', function() {
    loadSavedDevices();
    document.getElementById('new_mac').focus();
    
    // Set default dates (today and yesterday)
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);
    
    document.getElementById('start_date').value = yesterday.toISOString().split('T')[0];
    document.getElementById('end_date').value = today.toISOString().split('T')[0];
    
    // Add helpful tooltips
    document.getElementById('new_mac').title = 'Enter device MAC address in format: aa:bb:cc:dd:ee:ff';
    document.getElementById('hours_from').title = 'Enter starting hour (0 = midnight, 12 = noon)';
    document.getElementById('hours_to').title = 'Enter ending hour (23 = 11 PM)';
});

// Keyboard shortcuts
document.addEventListener('keydown', function(e) {
    if (e.ctrlKey && e.key === 'Enter') {
        document.getElementById('previewBtn').click();
    } else if (e.ctrlKey && e.key === 'd') {
        e.preventDefault();
        document.getElementById('downloadBtn').click();
    }
});