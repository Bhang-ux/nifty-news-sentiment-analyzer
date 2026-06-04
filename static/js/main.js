// static/js/main.js
document.addEventListener('DOMContentLoaded', function () {
    // --- DOM Element References (keep as before) ---
    const updateApiKeysBtn = document.getElementById('updateApiKeysBtn');
    const analysisForm = document.getElementById('analysisForm');
    const runAnalysisBtn = document.getElementById('runAnalysisBtn');
    const loadingIndicator = document.getElementById('loading-indicator');
    const logsOutput = document.getElementById('logs-output');
    const clearLogsBtn = document.getElementById('clearLogsBtn');
    const resultsSummaryDiv = document.getElementById('results-summary');
    const errorMessagesContainer = document.getElementById('error-messages-container');
    const errorList = document.getElementById('error-list');

    const sectorChartsContainer = document.getElementById('sector-charts-container');
    const sectorDetailsContainer = document.getElementById('sector-details-container');

    const analysisModeSelect = document.getElementById('analysis_mode_select');
    const batchSectorInputsDiv = document.getElementById('batch_sector_analysis_inputs_div');
    const adhocAnalysisScrapeInputsDiv = document.getElementById('adhoc_analysis_scrape_inputs_div');
    const adhocResultContainer = document.getElementById('adhoc-result-container');
    const adhocResultTitle = document.getElementById('adhoc-result-title');
    const adhocSentimentPriceChartCanvas = document.getElementById('adhocSentimentPriceChart');
    const adhocLlmAnalysisDetailsDiv = document.getElementById('adhoc-llm-analysis-details');
    const adhocArticlesTableBody = document.querySelector('#adhoc-articles-table tbody');
    
    const commonDateInputsDiv = document.getElementById('common_date_inputs');
    const commonLlmParamsDiv = document.getElementById('common_llm_params_div');

    let SECTOR_STOCK_CONFIG = {};
    // ... (SECTOR_STOCK_CONFIG parsing - keep as before) ...
    try {
        const configElement = document.getElementById('sectorStockConfig');
        if (configElement && configElement.textContent) {
            SECTOR_STOCK_CONFIG = JSON.parse(configElement.textContent);
        } else {
            console.warn("Sector-stock configuration not found in DOM.");
        }
    } catch (e) {
        console.error("Error parsing sector-stock configuration:", e);
    }


    const MAX_LOG_ENTRIES = 300;
    let currentLogEntries = [];
    let activeCharts = {}; // Stores all active Chart.js instances {canvasId: chartInstance}

    // --- Utility Functions (escapeHtml, appendToLog, renderLogs, displayErrorMessages - keep as before) ---
    function displayErrorMessages(messages) {
        errorList.innerHTML = '';
        if (messages && messages.length > 0) {
            messages.forEach(msg => {
                const li = document.createElement('li');
                li.textContent = String(msg); 
                errorList.appendChild(li);
            });
            errorMessagesContainer.style.display = 'block';
        } else {
            errorMessagesContainer.style.display = 'none';
        }
    }
    function escapeHtml(unsafe) {
        if (unsafe === null || typeof unsafe === 'undefined') return '';
        return unsafe.toString()
             .replace(/&/g, "&")
             .replace(/</g, "<")
             .replace(/>/g, ">")
             .replace(/"/g, '"')
             .replace(/'/g, "'");
    }
    function appendToLog(logEntry) { 
        currentLogEntries.push(logEntry);
        if (currentLogEntries.length > MAX_LOG_ENTRIES) currentLogEntries.shift(); 
        renderLogs();
    }
    function renderLogs() {
        logsOutput.innerHTML = ''; 
        currentLogEntries.forEach(logEntry => {
            const logElement = document.createElement('div');
            logElement.classList.add('log-entry');
            const levelStr = logEntry.level ? logEntry.level.toUpperCase() : 'UNKNOWN';
            logElement.innerHTML = `<span class="log-timestamp">[${logEntry.timestamp}]</span> <span class="log-level-${levelStr}">[${levelStr}]</span> ${escapeHtml(logEntry.message)}`;
            logsOutput.appendChild(logElement);
        });
        logsOutput.scrollTop = logsOutput.scrollHeight;
    }
    clearLogsBtn.addEventListener('click', () => {
        currentLogEntries = []; renderLogs(); 
        appendToLog({ timestamp: new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 }), message: "UI Logs cleared.", level: "INFO" });
    });

    // --- API Key Update (keep as before) ---
    updateApiKeysBtn.addEventListener('click', async () => {
        const geminiKeySess = document.getElementById('gemini_key_sess_in').value;
        const newsapiKeySess = document.getElementById('newsapi_key_sess_in').value;
        const payload = {};
        if (geminiKeySess) payload.gemini_key = geminiKeySess;
        if (newsapiKeySess) payload.newsapi_key = newsapiKeySess;
        const ts = new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
        if (Object.keys(payload).length === 0) {
            appendToLog({ timestamp: ts, message: "No API keys entered to update.", level: "WARNING" }); return;
        }
        loadingIndicator.style.display = 'block';
        try {
            const response = await fetch('/api/update-api-keys', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            const data = await response.json();
            appendToLog({ timestamp: ts, message: data.message || "API Key update response.", level: "INFO" });
            if (!response.ok) displayErrorMessages([data.message || `Error: ${response.status}`]);
            else displayErrorMessages([]);
        } catch (error) {
            appendToLog({ timestamp: ts, message: `Client error updating API keys: ${error}`, level: "ERROR" });
            displayErrorMessages([`Client error: ${error}`]);
        } finally {
            loadingIndicator.style.display = 'none';
        }
    });

    // --- UI Control & Form Submission (keep as before) ---
    analysisModeSelect.addEventListener('change', function() {
        const selectedMode = this.value;
        batchSectorInputsDiv.style.display = (selectedMode === 'sector_batch_analysis') ? 'block' : 'none';
        adhocAnalysisScrapeInputsDiv.style.display = (selectedMode === 'stock_adhoc_analysis_scrape') ? 'block' : 'none';
        commonDateInputsDiv.style.display = 'block';
        commonLlmParamsDiv.style.display = 'block';
        clearPreviousResults();
        resultsSummaryDiv.innerHTML = '<p>Configure and run an operation.</p>';
    });

    function clearPreviousResults() {
        Object.values(activeCharts).forEach(chart => { if (chart && typeof chart.destroy === 'function') chart.destroy(); });
        activeCharts = {};
        sectorChartsContainer.innerHTML = '';
        sectorDetailsContainer.innerHTML = '';
        adhocResultContainer.style.display = 'none';
        adhocResultTitle.textContent = '';
        if (adhocArticlesTableBody) adhocArticlesTableBody.innerHTML = '';
        adhocLlmAnalysisDetailsDiv.innerHTML = '';
        if (adhocSentimentPriceChartCanvas) {
            const ctx = adhocSentimentPriceChartCanvas.getContext('2d');
            ctx.clearRect(0, 0, adhocSentimentPriceChartCanvas.width, adhocSentimentPriceChartCanvas.height);
            const chartWrapper = adhocSentimentPriceChartCanvas.parentElement;
            const oldMsg = chartWrapper.querySelector('p.error-message'); if(oldMsg) oldMsg.remove();
        }
        displayErrorMessages([]);
    }

    analysisForm.addEventListener('submit', async function (event) {
        event.preventDefault();
        clearPreviousResults();
        runAnalysisBtn.disabled = true;
        loadingIndicator.style.display = 'block';
        resultsSummaryDiv.innerHTML = '<p>Processing request...</p>';
        const formData = new FormData(analysisForm);
        const data = {};
        formData.forEach((value, key) => {
            if (data[key]) {
                if (!Array.isArray(data[key])) data[key] = [data[key]];
                data[key].push(value);
            } else { data[key] = value; }
        });
        data.start_date = document.getElementById('start_date').value;
        data.end_date = document.getElementById('end_date').value;
        data.max_articles_llm = document.getElementById('max_articles_llm').value;
        data.custom_prompt_llm = document.getElementById('custom_prompt_llm').value;
        const operationMode = analysisModeSelect.value;
        const ts = new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
        appendToLog({ timestamp: ts, message: `Starting operation: ${operationMode}`, level: "INFO" });
        try {
            if (operationMode === 'sector_batch_analysis') {
                const batchPayload = {
                    selected_sectors: data.selected_sectors || [],
                    start_date: data.start_date, end_date: data.end_date,
                    sector_max_articles: data.max_articles_llm, 
                    sector_custom_prompt: data.custom_prompt_llm
                };
                await handleBatchSectorAnalysis(batchPayload);
            } else if (operationMode === 'stock_adhoc_analysis_scrape') {
                const adhocPayload = {
                    target_name: data.adhoc_target_name, target_type: data.adhoc_target_type,
                    start_date: data.start_date, end_date: data.end_date,
                    news_source_priority: data.adhoc_news_source,
                    trigger_scrape: data.trigger_adhoc_scrape === 'yes',
                    scrape_domains: data.trigger_adhoc_scrape === 'yes' ? (data.adhoc_scrape_domains || '').split(',').map(d => d.trim()).filter(d => d) : [],
                    max_articles_llm: data.max_articles_llm, custom_prompt_llm: data.custom_prompt_llm
                };
                await handleAdhocAnalysisAndScrape(adhocPayload);
            }
        } catch (error) {
            const ts_err = new Date().toLocaleTimeString([], { hour12: false });
            console.error(`Client error (${operationMode}):`, error);
            appendToLog({ timestamp: ts_err, message: `Client error (${operationMode}): ${error.message || error}`, level: "ERROR" });
            displayErrorMessages([`Client error (${operationMode}): ${error.message || 'Network error.'}`]);
            resultsSummaryDiv.innerHTML = `<p class="error-message">A client-side error occurred.</p>`;
        } finally {
            runAnalysisBtn.disabled = false; loadingIndicator.style.display = 'none';
        }
    });

    // --- Batch Sector Analysis Handler (modified for chart display) ---
    async function handleBatchSectorAnalysis(payload) {
        const response = await fetch('/api/sector-analysis', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (result.logs) result.logs.forEach(logEntry => appendToLog(logEntry));
        if (!response.ok || result.error) {
            displayErrorMessages(result.messages || (result.error && typeof result.error === 'string' ? [result.error] : [`Server error: ${response.status}.`]));
            resultsSummaryDiv.innerHTML = `<p class="error-message">Batch sector analysis failed.</p>`;
        } else {
            resultsSummaryDiv.innerHTML = `<p>Batch sector analysis complete. Found ${result.results ? result.results.length : 0} sector result(s).</p>`;
            displaySectorResultsAndStockOptions(result.results || []); // This function now handles charts
        }
    }
    
    // --- Adhoc Analysis & Scrape Handler (keep as before) ---
    async function handleAdhocAnalysisAndScrape(payload) { // (keep as provided in previous response)
        adhocResultContainer.style.display = 'block';
        adhocResultTitle.textContent = `Analysis for: ${escapeHtml(payload.target_name)}`;
        const response = await fetch('/api/adhoc-analysis-scrape', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (result.logs) result.logs.forEach(logEntry => appendToLog(logEntry));
        if (!response.ok || result.error) {
            displayErrorMessages(result.messages || (result.error && typeof result.error === 'string' ? [result.error] : [`Server error: ${response.status}.`]));
            resultsSummaryDiv.innerHTML = `<p class="error-message">Ad-hoc analysis/scrape failed.</p>`;
            adhocLlmAnalysisDetailsDiv.innerHTML = `<p class="error-message">Error fetching analysis.</p>`;
        } else {
            resultsSummaryDiv.innerHTML = `<p>Ad-hoc analysis for '${escapeHtml(result.target_name)}' complete. Fetched ${result.all_articles_fetched_count || 0} articles in total, analyzed ${result.articles_analyzed ? result.articles_analyzed.length : 0} with LLM.</p>`;
            if (result.llm_analysis) {
                adhocLlmAnalysisDetailsDiv.innerHTML = generateAdhocLlmDetailsHtml(result.llm_analysis, result.target_name);
            } else {
                adhocLlmAnalysisDetailsDiv.innerHTML = "<p>No LLM analysis available for this target.</p>";
            }
            if (adhocArticlesTableBody) {
                 adhocArticlesTableBody.innerHTML = '';
                 if (result.articles_analyzed && result.articles_analyzed.length > 0) {
                    result.articles_analyzed.forEach(article => {
                        const row = adhocArticlesTableBody.insertRow();
                        row.insertCell().textContent = article.date || 'N/A';
                        row.insertCell().textContent = article.source || 'N/A';
                        const contentCell = row.insertCell();
                        const snippet = (article.content || '').substring(0,100) + ((article.content || '').length > 100 ? '...' : '');
                        contentCell.innerHTML = `<a href="${escapeHtml(article.uri || '#')}" target="_blank" title="${escapeHtml(article.content)}">${escapeHtml(snippet) || 'N/A'}</a>`;
                        row.insertCell().textContent = (typeof article.vader_score === 'number') ? article.vader_score.toFixed(3) : 'N/A';
                        row.insertCell().textContent = 'N/A'; // Placeholder for per-article LLM
                    });
                 } else {
                    adhocArticlesTableBody.innerHTML = '<tr><td colspan="5">No articles were processed for LLM.</td></tr>';
                 }
            }
            if (result.daily_sentiment_data && (result.price_data || payload.target_type === 'sector')) {
                createOrUpdateAdhocSentimentPriceChart(result.daily_sentiment_data, result.price_data || [], result.target_name, payload.target_type);
            } else {
                appendToLog({timestamp: new Date().toLocaleTimeString([], { hour12: false }), message: "Data for rolling sentiment/price chart not fully available.", level: "WARNING"});
                if (activeCharts['adhocSentimentPriceChart']) activeCharts['adhocSentimentPriceChart'].destroy();
                const chartWrapper = adhocSentimentPriceChartCanvas.parentElement;
                const oldMsgP = chartWrapper.querySelector('p.error-message'); if(oldMsgP) oldMsgP.remove();
                const p = document.createElement('p'); p.textContent = "Sentiment/Price chart data not available."; p.classList.add('error-message');
                chartWrapper.appendChild(p);
            }
        }
    }
    
    // --- Adhoc LLM Details HTML (keep as before) ---
    function generateAdhocLlmDetailsHtml(llmAnalysis, targetName) { // (keep as provided in previous response)
        if (!llmAnalysis) return "<p>No LLM analysis data found.</p>";
        let html = `<h4>LLM Analysis for ${escapeHtml(targetName)}</h4>`;
        html += `<p><strong>Overall Sentiment:</strong> ${escapeHtml(llmAnalysis.overall_sentiment || 'N/A')} (Score: ${llmAnalysis.sentiment_score_llm !== null && typeof llmAnalysis.sentiment_score_llm !== 'undefined' ? parseFloat(llmAnalysis.sentiment_score_llm).toFixed(2) : 'N/A'})</p>`;
        html += `<p><strong>Summary:</strong> ${escapeHtml(llmAnalysis.summary || 'N/A')}</p>`;
        html += `<p><strong>Reason:</strong> ${escapeHtml(llmAnalysis.sentiment_reason || 'N/A')}</p>`;
        const createListHtml = (items, listTitle) => {
            if (items && Array.isArray(items) && items.length > 0 && items.some(item => String(item || '').trim() !== '')) {
                return `<strong>${listTitle}:</strong><ul>${items.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
            } return `<strong>${listTitle}:</strong> N/A`;
        };
        html += createListHtml(llmAnalysis.key_themes, 'Key Themes');
        html += `<p><strong>Potential Impact:</strong> ${escapeHtml(llmAnalysis.potential_impact || 'N/A')}</p>`;
        html += createListHtml(llmAnalysis.key_companies_mentioned_context, 'Companies/Context');
        html += createListHtml(llmAnalysis.risks_identified, 'Risks');
        html += createListHtml(llmAnalysis.opportunities_identified, 'Opportunities');
        return html;
    }

    // --- Adhoc Rolling Chart (keep as before) ---
    function createOrUpdateAdhocSentimentPriceChart(dailySentiment, priceData, targetName, targetType) { // (keep as provided in previous response)
        if (activeCharts['adhocSentimentPriceChart']) activeCharts['adhocSentimentPriceChart'].destroy();
        const chartWrapper = adhocSentimentPriceChartCanvas.parentElement;
        const oldMsg = chartWrapper.querySelector('.error-message'); if(oldMsg) oldMsg.remove();
        if (!dailySentiment || dailySentiment.length === 0) {
             const p = document.createElement('p'); p.textContent = "No daily sentiment data to plot."; p.classList.add('error-message');
             chartWrapper.appendChild(p); return;
        }
        const labels = dailySentiment.map(d => d.date);
        const sentimentScores = dailySentiment.map(d => d.avg_sentiment_score);
        const datasets = [{
            label: `${targetName} Avg Sentiment (VADER)`, data: sentimentScores,
            borderColor: 'rgb(75, 192, 192)', backgroundColor: 'rgba(75, 192, 192, 0.2)',
            yAxisID: 'ySentiment', tension: 0.1, fill: true
        }];
        const scales = {
            x: { type: 'time', time: { unit: 'day', tooltipFormat: 'MMM dd, yyyy', parser: 'yyyy-MM-dd' }, title: { display: true, text: 'Date' } },
            ySentiment: { type: 'linear', display: true, position: 'left', min: -1, max: 1, title: { display: true, text: 'Avg. VADER Score' } }
        };
        if (targetType === 'stock' && priceData && priceData.length > 0) {
            const alignedPrices = labels.map(labelDate => {
                const priceEntry = priceData.find(p => p.date === labelDate);
                return priceEntry ? priceEntry.close_price : null;
            });
            datasets.push({
                label: `${targetName} Closing Price`, data: alignedPrices,
                borderColor: 'rgb(255, 99, 132)', backgroundColor: 'rgba(255, 99, 132, 0.2)',
                yAxisID: 'yPrice', tension: 0.1, type: 'line', fill: false
            });
            scales.yPrice = {
                type: 'linear', display: true, position: 'right',
                title: { display: true, text: 'Stock Price' }, grid: { drawOnChartArea: false }
            };
        }
        const ctx = adhocSentimentPriceChartCanvas.getContext('2d');
        activeCharts['adhocSentimentPriceChart'] = new Chart(ctx, {
            type: 'line', data: { labels: labels, datasets: datasets },
            options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false, }, scales: scales, plugins: { title: { display: true, text: `Daily Sentiment ${targetType === 'stock' ? '& Price ' : ''}for ${targetName}` }, legend: { display: true } } }
        });
    }

    // --- Batch Sector Analysis: Display and Sub-Stock Logic ---
    // MODIFIED: createSentimentChart for Batch Sector
    function createBatchSectorSentimentChart(canvasId, llmScore, vaderScore, sectorName) {
        console.log(`Creating chart for ${sectorName} on canvas ${canvasId} with LLM: ${llmScore}, VADER: ${vaderScore}`);
        const chartLabels = [];
        const chartDataPoints = [];
        const chartBackgroundColors = [];
        const chartBorderColors = [];

        if (typeof llmScore === 'number' && !isNaN(llmScore)) {
            chartLabels.push('LLM Overall');
            chartDataPoints.push(llmScore);
            chartBackgroundColors.push(llmScore > 0.1 ? 'rgba(75, 192, 192, 0.6)' : llmScore < -0.1 ? 'rgba(255, 99, 132, 0.6)' : 'rgba(201, 203, 207, 0.6)');
            chartBorderColors.push(llmScore > 0.1 ? 'rgba(75, 192, 192, 1)' : llmScore < -0.1 ? 'rgba(255, 99, 132, 1)' : 'rgba(201, 203, 207, 1)');
        }
        if (typeof vaderScore === 'number' && !isNaN(vaderScore)) {
            chartLabels.push('VADER Avg. (Batch)');
            chartDataPoints.push(vaderScore);
            chartBackgroundColors.push(vaderScore > 0.05 ? 'rgba(54, 162, 235, 0.6)' : vaderScore < -0.05 ? 'rgba(255, 159, 64, 0.6)' : 'rgba(153, 102, 255, 0.6)');
            chartBorderColors.push(vaderScore > 0.05 ? 'rgba(54, 162, 235, 1)' : vaderScore < -0.05 ? 'rgba(255, 159, 64, 1)' : 'rgba(153, 102, 255, 1)');
        }

        const canvasElement = document.getElementById(canvasId);
        if (!canvasElement) {
            console.error(`[createBatchSectorSentimentChart] Canvas element with ID '${canvasId}' not found for sector ${sectorName}.`);
            // Attempt to place an error message in the chart wrapper if the wrapper exists.
            const wrapper = document.getElementById(`chart-wrapper-${canvasId.split('-')[1]}`); // Assuming ID like sectorChart-0
            if (wrapper) {
                const p = document.createElement('p');
                p.textContent = `Chart canvas '${canvasId}' missing.`;
                p.classList.add('error-message');
                wrapper.appendChild(p);
            }
            return null;
        }
        if (chartDataPoints.length === 0) {
            console.warn(`[createBatchSectorSentimentChart] No data points to plot for ${sectorName} on ${canvasId}.`);
             const p = document.createElement('p');
             p.textContent = "No sentiment scores available for chart.";
             p.classList.add('error-message');
             // Replace canvas with message if its parent is the chart-wrapper
             if (canvasElement.parentElement && canvasElement.parentElement.classList.contains('chart-wrapper')) {
                const oldMsg = canvasElement.parentElement.querySelector('.error-message'); if(oldMsg) oldMsg.remove();
                canvasElement.parentElement.appendChild(p);
             }
            return null;
        }

        const ctx = canvasElement.getContext('2d');
        if (activeCharts[canvasId]) {
            activeCharts[canvasId].destroy();
            console.log(`Destroyed existing chart on ${canvasId}`);
        }
        activeCharts[canvasId] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: chartLabels,
                datasets: [{ label: 'Sentiment Score', data: chartDataPoints, backgroundColor: chartBackgroundColors, borderColor: chartBorderColors, borderWidth: 1 }]
            },
            options: {
                responsive: true, maintainAspectRatio: false, indexAxis: 'y',
                scales: { x: { beginAtZero: false, min: -1, max: 1, title: { display: true, text: 'Score (-1 to 1)' } } },
                plugins: { legend: { display: chartLabels.length > 1 }, title: { display: false } } // Title is in H4
            }
        });
        console.log(`Successfully created chart for ${sectorName} on ${canvasId}`);
        return activeCharts[canvasId];
    }

    // MODIFIED: displaySectorResultsAndStockOptions for correct chart rendering
    function displaySectorResultsAndStockOptions(allSectorResults) {
        sectorChartsContainer.innerHTML = ''; 
        sectorDetailsContainer.innerHTML = '';
        if (!allSectorResults || allSectorResults.length === 0) {
            sectorDetailsContainer.innerHTML = "<p>No batch sector results to display.</p>"; return;
        }

        allSectorResults.forEach((sectorData, sectorIndex) => {
            const sectorNameSafe = escapeHtml(sectorData.sector_name);
            const chartWrapperId = `chart-wrapper-${sectorIndex}`; // Unique ID for the wrapper
            const sectorCanvasId = `sectorChart-${sectorIndex}`;   // Unique ID for the canvas

            const sectorChartWrapper = document.createElement('div');
            sectorChartWrapper.classList.add('chart-wrapper');
            sectorChartWrapper.id = chartWrapperId; // Assign ID to wrapper
            
            const sectorCanvas = document.createElement('canvas');
            sectorCanvas.id = sectorCanvasId;
            // Canvas itself doesn't need fixed height here if wrapper controls it via CSS

            let sLlmScoreVal = sectorData.gemini_analysis_sector ? sectorData.gemini_analysis_sector.sentiment_score_llm : null;
            let sVaderScoreVal = sectorData.avg_vader_score_sector;
            let sLlmDisp = (typeof sLlmScoreVal === 'number' && !isNaN(sLlmScoreVal)) ? sLlmScoreVal.toFixed(2) : 'N/A';
            let sVaderDisp = (typeof sVaderScoreVal === 'number' && !isNaN(sVaderScoreVal)) ? sVaderScoreVal.toFixed(2) : 'N/A';
            
            const sChartTitleEl = document.createElement('h4');
            sChartTitleEl.innerHTML = `SECTOR: ${sectorNameSafe} <small>(LLM: ${sLlmDisp}, VADER: ${sVaderDisp})</small>`;
            
            sectorChartWrapper.appendChild(sChartTitleEl);
            sectorChartWrapper.appendChild(sectorCanvas); // Append canvas to wrapper
            sectorChartsContainer.appendChild(sectorChartWrapper); // Append wrapper to main charts container

            // Create chart AFTER canvas is in the DOM
            createBatchSectorSentimentChart(sectorCanvasId, sLlmScoreVal, sVaderScoreVal, sectorNameSafe);

            // --- Details and Sub-Stock UI (keep as before) ---
            const sDetailItem = document.createElement('div'); 
            sDetailItem.classList.add('result-item', 'sector-result-item');
            let sDetailHtml = `<h3>SECTOR: ${sectorNameSafe}</h3>`;
            sDetailHtml += `<p><small>Context: ${escapeHtml(sectorData.llm_context_date_range || 'N/A')} | Articles for LLM: ${sectorData.num_articles_for_llm_sector !== undefined ? sectorData.num_articles_for_llm_sector : 'N/A'}</small></p>`;
            sDetailHtml += generateAnalysisDetailHtml(sectorData, sectorData.sector_name, "sector"); // Make sure this function is defined correctly
            
            const stockContainer = document.createElement('div'); 
            stockContainer.classList.add('stock-analysis-trigger-container'); 
            stockContainer.id = `stock-analysis-container-${sectorIndex}`;
            if (sectorData.constituent_stocks && sectorData.constituent_stocks.length > 0) {
                const stockLabel = document.createElement('label'); stockLabel.htmlFor = `stock-select-${sectorIndex}`; stockLabel.textContent = `Analyze Stocks for ${sectorNameSafe}:`;
                const stockSelect = document.createElement('select'); stockSelect.multiple = true; stockSelect.id = `stock-select-${sectorIndex}`; stockSelect.size = Math.min(sectorData.constituent_stocks.length, 5);
                sectorData.constituent_stocks.forEach(stock => { const opt = document.createElement('option'); opt.value = stock; opt.textContent = escapeHtml(stock); stockSelect.appendChild(opt); });
                const runStockBtn = document.createElement('button'); runStockBtn.textContent = `Analyze Selected Stocks`; runStockBtn.classList.add('run-stock-analysis-btn');
                runStockBtn.dataset.sectorName = sectorData.sector_name; runStockBtn.dataset.sectorIndex = sectorIndex;
                stockContainer.append(stockLabel, stockSelect, runStockBtn);
                const stockResultsArea = document.createElement('div'); stockResultsArea.id = `stock-results-display-${sectorIndex}`; stockResultsArea.classList.add('stock-results-area');
                stockContainer.appendChild(stockResultsArea);
            } else { stockContainer.innerHTML = `<p><em>No constituent stocks for this sector.</em></p>`; }
            sDetailItem.appendChild(stockContainer); 
            sectorDetailsContainer.appendChild(sDetailItem);
        });
        document.querySelectorAll('.run-stock-analysis-btn').forEach(btn => btn.addEventListener('click', handleRunSubStockAnalysis));
    }

    // MODIFIED: generateAnalysisDetailHtml for clarity on batch vs. individual
    function generateAnalysisDetailHtml(analysisData, targetName, targetType = "sector", analysisScope = "Batch") {
        let detailHtml = '';
        const geminiAnalysis = (targetType === "sector") ? analysisData.gemini_analysis_sector : analysisData.gemini_analysis_stock;
        const avgVaderScore = (targetType === "sector") ? analysisData.avg_vader_score_sector : analysisData.avg_vader_score_stock;
        const vaderSentimentLabel = (targetType === "sector") ? analysisData.vader_sentiment_label_sector : analysisData.vader_sentiment_label_stock;
        const numArticles = (targetType === "sector") ? analysisData.num_articles_for_llm_sector : analysisData.num_articles_for_llm_stock;
        const errorMessage = (targetType === "sector") ? analysisData.error_message_sector : analysisData.error_message_stock;

        if (targetType === "stock") detailHtml += `<p><small>Articles for LLM (${analysisScope}): ${numArticles !== undefined ? numArticles : 'N/A'}</small></p>`;
        if (errorMessage) detailHtml += `<p class="error-message"><strong>Error:</strong> ${escapeHtml(errorMessage)}</p>`;
        
        if (typeof avgVaderScore === 'number' && !isNaN(avgVaderScore)) {
            detailHtml += `<p><strong>VADER Avg. (${analysisScope}):</strong> ${escapeHtml(vaderSentimentLabel || 'N/A')} (Score: ${parseFloat(avgVaderScore).toFixed(3)})</p>`;
        } else {
            detailHtml += `<p><strong>VADER Avg. (${analysisScope}):</strong> N/A</p>`;
        }
        
        if (geminiAnalysis) {
            const llmScore = geminiAnalysis.sentiment_score_llm;
            detailHtml += `<p><strong>LLM Overall (${analysisScope}):</strong> ${escapeHtml(geminiAnalysis.overall_sentiment || 'N/A')} (Score: ${llmScore !== null && typeof llmScore !== 'undefined' && !isNaN(llmScore) ? parseFloat(llmScore).toFixed(2) : 'N/A'})</p>`;
            detailHtml += `<p><strong>LLM Summary (${analysisScope}):</strong> ${escapeHtml(geminiAnalysis.summary || 'N/A')}</p>`;
            detailHtml += `<p><strong>LLM Reason (${analysisScope}):</strong> ${escapeHtml(geminiAnalysis.sentiment_reason || 'N/A')}</p>`;
            const createListHtml = (items, listTitle) => {
                if (items && Array.isArray(items) && items.length > 0 && items.some(item => String(item || '').trim() !== '')) {
                    return `<strong>${listTitle} (${analysisScope}):</strong><ul>${items.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
                } return `<strong>${listTitle} (${analysisScope}):</strong> N/A`;
            };
            detailHtml += createListHtml(geminiAnalysis.key_themes, 'LLM Key Themes');
            detailHtml += `<p><strong>LLM Potential Impact (${analysisScope}):</strong> ${escapeHtml(geminiAnalysis.potential_impact || 'N/A')}</p>`;
            detailHtml += createListHtml(geminiAnalysis.key_companies_mentioned_context, 'LLM Companies/Context');
            detailHtml += createListHtml(geminiAnalysis.risks_identified, 'LLM Risks');
            detailHtml += createListHtml(geminiAnalysis.opportunities_identified, 'LLM Opportunities');
        } else if (!errorMessage) {
            detailHtml += `<p>No LLM analysis data available for this ${targetType} (${analysisScope}).</p>`;
        }
        return detailHtml;
    }
    
    // MODIFIED: handleRunSubStockAnalysis to use common form fields correctly
    async function handleRunSubStockAnalysis(event) {
        const button = event.target; 
        const sectorName = button.dataset.sectorName; 
        const sectorIndex = button.dataset.sectorIndex;
        const stockSelectEl = document.getElementById(`stock-select-${sectorIndex}`);
        const selectedStocks = Array.from(stockSelectEl.selectedOptions).map(opt => opt.value);
        if (selectedStocks.length === 0) { alert(`Please select stocks for ${sectorName}.`); return; }
        
        button.disabled = true; 
        loadingIndicator.style.display = 'block';
        
        const commonStartDate = document.getElementById('start_date').value;
        const commonEndDate = document.getElementById('end_date').value;
        // Calculate lookback days based on the common start and end dates
        let lookbackDays = 7; // Default
        if (commonStartDate && commonEndDate) {
            const startDateObj = new Date(commonStartDate);
            const endDateObj = new Date(commonEndDate);
            if (endDateObj >= startDateObj) {
                lookbackDays = Math.round((endDateObj - startDateObj) / (1000 * 60 * 60 * 24)) + 1;
            }
        }
        
        const payload = {
            sector_name: sectorName, 
            selected_stocks: selectedStocks,
            start_date: commonStartDate, // Use common start_date
            end_date: commonEndDate,     // Use common end_date
            // lookback_days is derived by the backend from start/end or uses a default if needed
            stock_max_articles: document.getElementById('max_articles_llm').value, 
            custom_prompt: document.getElementById('custom_prompt_llm').value 
        };
        appendToLog({ timestamp: new Date().toLocaleTimeString([], { hour12: false }), message: `Starting sub-stock analysis for ${sectorName} (${selectedStocks.join(', ')}). Dates: ${commonStartDate}-${commonEndDate}`, level: "INFO" });
        try {
            const response = await fetch('/api/stock-analysis', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            const result = await response.json();
            if (result.logs) result.logs.forEach(log => appendToLog(log));
            const stockResultsDisplayArea = document.getElementById(`stock-results-display-${sectorIndex}`); 
            stockResultsDisplayArea.innerHTML = '';
            if (!response.ok || result.error) {
                displayErrorMessages(result.messages || [`Sub-stock analysis server error: ${response.status}`]);
                stockResultsDisplayArea.innerHTML = `<p class="error-message">Sub-stock analysis failed.</p>`;
            } else {
                displayIndividualStockResults(result.results_stocks || [], stockResultsDisplayArea);
            }
        } catch (error) {
            console.error(`Error (sub-stock analysis ${sectorName}):`, error);
            appendToLog({ timestamp: new Date().toLocaleTimeString([], { hour12: false }), message: `Client error (sub-stock analysis): ${error}`, level: "ERROR" });
            document.getElementById(`stock-results-display-${sectorIndex}`).innerHTML = `<p class="error-message">Client error during sub-stock analysis.</p>`;
        } finally {
            button.disabled = false; 
            loadingIndicator.style.display = 'none';
        }
    }

    // MODIFIED: displayIndividualStockResults to use updated generateAnalysisDetailHtml
    function displayIndividualStockResults(stockResults, containerElement) {
        if (!stockResults || stockResults.length === 0) {
            containerElement.innerHTML = "<p><em>No analysis results for selected stocks.</em></p>"; return;
        }
        const stockListHtml = stockResults.map(stockData => {
            let html = `<div class="result-item stock-result-item">`; // Ensure these classes are styled
            let sLlmScore = stockData.gemini_analysis_stock ? stockData.gemini_analysis_stock.sentiment_score_llm : null;
            let sVaderScore = stockData.avg_vader_score_stock;
            html += `<h5>${escapeHtml(stockData.stock_name)} <small>(LLM ${sLlmScore !== null ? sLlmScore.toFixed(2):'N/A'}, VADER ${sVaderScore !==null ? sVaderScore.toFixed(2):'N/A'})</small></h5>`;
            // Pass "Stock Batch" or similar to distinguish from overall sector batch
            html += generateAnalysisDetailHtml(stockData, stockData.stock_name, "stock", "Stock Analysis"); 
            html += `</div>`;
            return html;
        }).join('');
        containerElement.innerHTML = `<div class="stock-list-container">${stockListHtml}</div>`;
    }

    // Initial UI Setup
    analysisModeSelect.dispatchEvent(new Event('change'));
    appendToLog({ timestamp: new Date().toLocaleTimeString([], { hour12: false }), message: "Frontend initialized. Ready.", level: "INFO" });
});