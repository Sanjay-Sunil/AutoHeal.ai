import React, { useState, useRef, useEffect } from 'react';

function App() {
    const [apiMode, setApiMode] = useState('LEGACY');
    const [logs, setLogs] = useState([{ message: 'System initialized. Waiting for traffic...', type: 'info', time: new Date().toLocaleTimeString() }]);
    const consoleEndRef = useRef(null);

    useEffect(() => {
        consoleEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [logs]);

    const logMessage = (message, type = 'info') => {
        const time = new Date().toLocaleTimeString();
        setLogs(prev => [...prev, { message, type, time }]);
    };

    const mockVendorAPI = async (payload, currentMode) => {
        return new Promise((resolve, reject) => {
            setTimeout(() => {
                if (currentMode === 'LEGACY') {
                    if (payload.amount && payload.currency) {
                        resolve({ status: 200, data: { status: "success", tx_id: "tx_123" } });
                    } else {
                        reject({ status: 400, error: "Missing 'amount' or 'currency'" });
                    }
                } else if (currentMode === 'UPGRADED') {
                    if (payload.payment_details && payload.payment_details.total_amount) {
                        resolve({ status: 200, data: { payment_status: "captured", ref: "tx_999" } });
                    } else {
                        reject({
                            status: 400,
                            error: "Schema Validation Failed: Expected nested 'payment_details'",
                            expected: { payment_details: { total_amount: "float" } }
                        });
                    }
                }
            }, 400);
        });
    };

    // We use a ref to hold the latest API mode to use within the setTimeout scopes securely without closures being stale,
    // alternatively just passing it directly where possible.
    const apiModeRef = useRef(apiMode);
    useEffect(() => {
        apiModeRef.current = apiMode;
    }, [apiMode]);

    const smartInterceptor = async (originalPayload) => {
        logMessage(`[App] Sending request: ${JSON.stringify(originalPayload)}`, 'info');

        try {
            await mockVendorAPI(originalPayload, apiModeRef.current);
            logMessage(`[Gateway] 200 OK - Payment successful!`, 'success');
            alert("Payment Successful!");
        } catch (err) {
            logMessage(`[Gateway] ${err.status || 500} ERROR: ${err.error || 'Unknown'}`, 'error');
            logMessage(`[Interceptor] Trapped error. Engaging AI remediation loop...`, 'ai');

            setTimeout(async () => {
                logMessage(`[Interceptor] AI generated hotfix mapping: payload -> payment_details`, 'ai');

                const healedPayload = {
                    payment_details: {
                        total_amount: originalPayload.amount / 100,
                        currency_code: originalPayload.currency
                    }
                };

                logMessage(`[Interceptor] Replaying request with healed payload: ${JSON.stringify(healedPayload)}`, 'ai');

                try {
                    await mockVendorAPI(healedPayload, apiModeRef.current);
                    logMessage(`[Gateway] 200 OK - Recovered!`, 'success');
                    logMessage(`[Dashboard] Generating PR for permanent code fix.`, 'info');
                    alert("Payment auto-recovered and succeeded!");
                } catch (fatalErr) {
                    logMessage(`[Interceptor] Auto-heal failed.`, 'error');
                }
            }, 1000);
        }
    };

    const toggleMode = () => {
        if (apiMode === 'LEGACY') {
            setApiMode('UPGRADED');
            logMessage('🚨 Admin triggered unannounced API schema drift to V2', 'error');
        } else {
            setApiMode('LEGACY');
            logMessage('✅ Admin reverted gateway to Legacy V1', 'success');
        }
    };

    const handleCheckout = () => {
        const payload = { amount: 5000, currency: "INR" };
        smartInterceptor(payload);
    };

    const clearLogs = () => {
        setLogs([]);
        logMessage('Console cleared.', 'info');
    };

    const getLogColorClass = (type) => {
        if (type === 'error') return 'text-red-400';
        if (type === 'success') return 'text-green-400';
        if (type === 'ai') return 'text-purple-400 font-bold';
        return 'text-slate-300';
    };

    return (
        <div className="p-8">
            <div className="max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-2 gap-8">

                <div className="space-y-8">

                    <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
                        <h2 className="text-xl font-bold text-slate-800 mb-2">⚙️ Third-Party Gateway Admin</h2>
                        <p className="text-sm text-slate-500 mb-4">Simulate unannounced API schema drift by toggling the vendor's required format.</p>

                        <div className="flex items-center justify-between bg-slate-100 p-4 rounded-lg">
                            <div>
                                <span className="text-xs font-semibold uppercase text-slate-500">Current API Mode</span>
                                <div className={`text-lg font-bold mt-1 ${apiMode === 'LEGACY' ? 'text-emerald-600' : 'text-red-600'}`}>
                                    {apiMode === 'LEGACY' ? 'LEGACY (V1)' : 'UPGRADED (V2)'}
                                </div>
                            </div>
                            <button onClick={toggleMode} className="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded shadow transition font-medium">
                                {apiMode === 'LEGACY' ? 'Trigger Schema Drift' : 'Revert to Legacy'}
                            </button>
                        </div>
                        <div className="mt-4 text-xs font-mono bg-slate-800 text-green-400 p-3 rounded">
                            Expected: <span>{apiMode === 'LEGACY' ? '{"amount": 5000, "currency": "INR"}' : '{"payment_details": {"total_amount": 50.00}}'}</span>
                        </div>
                    </div>

                    <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200 border-t-4 border-t-blue-500">
                        <h2 className="text-xl font-bold text-slate-800 mb-2">🛒 Our Internal App</h2>
                        <p className="text-sm text-slate-500 mb-4">This app always sends the Legacy V1 format. It does not know if the gateway updates.</p>

                        <div className="p-4 border rounded-lg bg-blue-50/50 flex justify-between items-center">
                            <div>
                                <h3 className="font-bold text-slate-700">Premium Subscription</h3>
                                <p className="text-sm text-slate-500">₹50.00 INR</p>
                            </div>
                            <button onClick={handleCheckout} className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-full shadow transition font-medium">
                                Pay Now
                            </button>
                        </div>
                    </div>

                </div>

                <div className="bg-slate-900 rounded-xl shadow-lg border border-slate-700 flex flex-col h-[600px] overflow-hidden">
                    <div className="bg-slate-800 px-4 py-3 border-b border-slate-700 flex justify-between items-center">
                        <h2 className="text-sm font-bold text-slate-200">Terminal: Interceptor Logs</h2>
                        <button onClick={clearLogs} className="text-xs text-slate-400 hover:text-white transition">Clear</button>
                    </div>
                    <div className="p-4 overflow-y-auto flex-1 font-mono text-xs space-y-2">
                        {logs.map((log, index) => (
                            <div key={index} className={getLogColorClass(log.type)}>
                                <span className="text-slate-600">[{log.time}]</span> {log.message}
                            </div>
                        ))}
                        <div ref={consoleEndRef} />
                    </div>
                </div>
            </div>
        </div>
    );
}

export default App;
