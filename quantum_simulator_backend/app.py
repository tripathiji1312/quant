import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import numpy as np # For statevector calculations

# Ensure qiskit and qiskit_aer are importable
try:
    from qiskit import QuantumCircuit, transpile
    import qiskit  # For qiskit.circuit.ClassicalRegister, qiskit.circuit.Clbit
    from qiskit_aer import AerSimulator
    from qiskit.quantum_info import Statevector # For statevector analysis
except ImportError as e:
    print(f"CRITICAL ERROR: Qiskit or Qiskit Aer is not installed correctly: {e}")
    print(
        "Please ensure you have a working Python environment (e.g., 3.11 or 3.12) where 'pip install qiskit qiskit-aer' succeeds fully.")
    raise

from qiskit_ibm_runtime import QiskitRuntimeService, Options

load_dotenv()

app = Flask(__name__)
CORS(app)

IBM_API_KEY = os.getenv("IBM_QUANTUM_API_KEY")
CHANNEL = os.getenv("IBM_QUANTUM_CHANNEL", "ibm_cloud").lower()
INSTANCE_FROM_ENV = os.getenv("IBM_QUANTUM_INSTANCE")
if INSTANCE_FROM_ENV == "":
    INSTANCE_FROM_ENV = None

service = None
ibm_simulators_available = False

if IBM_API_KEY:
    print(f"Attempting to initialize Qiskit Runtime Service with CHANNEL='{CHANNEL}'...")
    if INSTANCE_FROM_ENV:
        print(f"INSTANCE from .env: '{INSTANCE_FROM_ENV}'")
    else:
        print("INSTANCE not set in .env.")
    try:
        save_args = {"token": IBM_API_KEY, "channel": CHANNEL, "overwrite": True}
        if INSTANCE_FROM_ENV: save_args["instance"] = INSTANCE_FROM_ENV
        QiskitRuntimeService.save_account(**save_args)
        print(f"Account details saved/updated for channel='{CHANNEL}', instance='{save_args.get('instance', 'N/A')}'")

        if INSTANCE_FROM_ENV:
            service = QiskitRuntimeService(channel=CHANNEL, instance=INSTANCE_FROM_ENV)
        else:
            service = QiskitRuntimeService(channel=CHANNEL)
        print(f"Service instantiated with channel='{CHANNEL}', instance='{INSTANCE_FROM_ENV if INSTANCE_FROM_ENV else 'N/A'}'.")
        
        print("--- DIAGNOSTIC: Listing ALL backends for the current service configuration ---")
        try:
            all_backends_diagnostic = service.backends(instance=INSTANCE_FROM_ENV if INSTANCE_FROM_ENV else None)
            if not all_backends_diagnostic: print("DIAGNOSTIC: No backends found.")
            else:
                print(f"DIAGNOSTIC: Found {len(all_backends_diagnostic)} backends:")
                for i, b in enumerate(all_backends_diagnostic):
                    status_name = b.status.name if hasattr(b, 'status') and b.status else "N/A"
                    simulator_flag = b.simulator if hasattr(b, 'simulator') else "N/A"
                    print(f"  {i + 1}. Name: {b.name}, Version: {b.backend_version if hasattr(b, 'backend_version') else 'N/A'}, Status: {status_name}, Simulator: {simulator_flag}")
                    if i >= 9: print("     ... (list truncated) ..."); break
        except Exception as diag_e: print(f"DIAGNOSTIC: Error listing all backends: {diag_e}")
        print("--- END DIAGNOSTIC ---")

        sim_backends = service.backends(simulator=True, operational=True, instance=INSTANCE_FROM_ENV if INSTANCE_FROM_ENV else None)
        if sim_backends:
            ibm_simulators_available = True
            sample_names = [b.name for b in sim_backends[:3]]
            print(f"IBM Quantum Runtime Service: Found operational simulators: {sample_names}")
        else:
            print(f"Warning: No operational IBM Quantum simulators found for channel='{CHANNEL}', instance='{INSTANCE_FROM_ENV if INSTANCE_FROM_ENV else 'N/A'}'. Will use local Aer simulator for counts if IBM fails.")
    except Exception as e:
        import traceback
        print(f"Failed to initialize Qiskit Runtime Service or find IBM backends: {e}")
        if "Provided API key could not be found" in str(e): print("Hint: API key might be invalid for the channel.")
        print("--- Full Traceback for Initialization Error ---"); traceback.print_exc(); print("--- End Traceback ---")
        service = None
else:
    print("IBM_QUANTUM_API_KEY not found. Will use local Aer simulator if possible.")


@app.route('/simulate', methods=['POST'])
def simulate_circuit_for_counts(): # Renamed for clarity
    data = request.get_json()
    if not data or 'qasm' not in data:
        return jsonify({"error": "Missing 'qasm' in request body"}), 400

    qasm_code = data['qasm']
    shots = data.get('shots', 1024)
    requested_ibm_backend_name = data.get('backend', 'ibmq_qasm_simulator')

    try:
        circuit = QuantumCircuit.from_qasm_str(qasm_code)
        print(f"Counts Sim: Circuit from QASM. Qubits: {circuit.num_qubits}, Classical Bits: {circuit.num_clbits}")
    except Exception as qasm_err:
        return jsonify({"error": f"Invalid QASM input: {qasm_err}"}), 400

    has_measure_ops_in_qasm = any(instr.operation.name == 'measure' for instr in circuit.data)
    if not has_measure_ops_in_qasm:
        if circuit.num_qubits > 0:
            if circuit.num_clbits < circuit.num_qubits:
                while circuit.cregs: circuit.remove_register(circuit.cregs[0])
                creg_measure_all = qiskit.circuit.ClassicalRegister(circuit.num_qubits, 'c_auto')
                circuit.add_register(creg_measure_all)
            circuit.measure_all(inplace=True)
            print("Counts Sim: measure_all() added.")
    else:
        print("Counts Sim: Circuit from QASM already contains measurement operations.")
        max_clbit_measured = -1
        for instr in circuit.data:
            if instr.operation.name == 'measure':
                for clbit in instr.clbits:
                    if clbit.index > max_clbit_measured: max_clbit_measured = clbit.index
        if max_clbit_measured != -1 and circuit.num_clbits <= max_clbit_measured:
            print(f"Warning: QASM measures up to cbit {max_clbit_measured} but circuit has {circuit.num_clbits} clbits.")

    if service and ibm_simulators_available:
        selected_ibm_backend_obj = None
        actual_ibm_backend_name = None
        try:
            backend_instance_filter = INSTANCE_FROM_ENV if INSTANCE_FROM_ENV else None
            try:
                selected_ibm_backend_obj = service.backend(name=requested_ibm_backend_name, instance=backend_instance_filter)
                actual_ibm_backend_name = selected_ibm_backend_obj.name
            except Exception:
                sims = service.backends(simulator=True, operational=True, instance=backend_instance_filter)
                if not sims: raise ValueError("No IBM simulators available now.")
                selected_ibm_backend_obj = sims[0]
                actual_ibm_backend_name = selected_ibm_backend_obj.name
            
            print(f"Counts Sim: Transpiling for IBM backend: {actual_ibm_backend_name}")
            transpiled_circuit = transpile(circuit, backend=selected_ibm_backend_obj)
            program_inputs = {'circuits': transpiled_circuit, 'run_options': {'shots': shots}}
            print(f"Counts Sim: Running on IBM backend {actual_ibm_backend_name} via circuit-runner...")
            job = service.run(program_id="circuit-runner", options={'backend': actual_ibm_backend_name}, inputs=program_inputs)
            result = job.result()
            counts = {}
            if hasattr(result, 'quasi_dists') and result.quasi_dists:
                counts_data = result.quasi_dists[0]
                num_clbits_for_counts = transpiled_circuit.num_clbits if transpiled_circuit.num_clbits > 0 else circuit.num_qubits
                if num_clbits_for_counts > 0:
                    counts = {f"{int(key):0{num_clbits_for_counts}b}": int(value * shots) for key, value in counts_data.items()}
                else: # Should not happen if there are measurements
                    counts = {str(key): int(value * shots) for key, value in counts_data.items()}
            elif hasattr(result, 'get_counts'): counts = result.get_counts(transpiled_circuit)
            elif isinstance(result, list) and result and hasattr(result[0], 'data') and hasattr(result[0].data, 'counts'): counts = result[0].data.counts
            
            print(f"Counts Sim: IBM Job successful. Counts: {counts}")
            return jsonify({"message": "Simulation successful (IBM Quantum)!", "job_id": job.job_id(), "backend_used": actual_ibm_backend_name, "shots": shots, "counts": counts})
        except Exception as ibm_run_err:
            print(f"Counts Sim: Error during IBM Quantum execution: {ibm_run_err}. Falling back to local Aer.")
    
    print("Counts Sim: Using local Qiskit Aer simulator.")
    try:
        aer_sim = AerSimulator()
        print(f"Counts Sim: Running on Aer. Circuit num_qubits: {circuit.num_qubits}, num_clbits: {circuit.num_clbits}")
        job = aer_sim.run(circuit, shots=shots)
        result = job.result()
        counts = result.get_counts(circuit)
        print(f"Counts Sim: Local Aer simulation successful. Counts: {counts}")
        return jsonify({"message": "Simulation successful (Local Aer)!", "backend_used": "local_aer_simulator", "shots": shots, "counts": counts})
    except Exception as aer_err:
        import traceback
        print(f"Counts Sim: Error during local Aer simulation: {aer_err}"); traceback.print_exc()
        return jsonify({"error": f"Error during local Aer simulation: {aer_err}"}), 500

# --- NEW ENDPOINT: Get Statevector ---
@app.route('/get_statevector', methods=['POST'])
def get_statevector_endpoint():
    data = request.get_json()
    if not data or 'qasm' not in data:
        return jsonify({"error": "Missing 'qasm' in request body"}), 400
    qasm_code = data['qasm']
    try:
        circuit = QuantumCircuit.from_qasm_str(qasm_code)
        # Remove any measurements if present, as statevector is pre-measurement
        circuit.remove_final_measurements(inplace=True) # Modifies circuit
        
        print(f"Statevector: Circuit from QASM. Qubits: {circuit.num_qubits}")
        if circuit.num_qubits == 0:
            return jsonify({"error": "Circuit has no qubits for statevector."}), 400
        if circuit.num_qubits > 16: # Aer statevector can get very large
             return jsonify({"error": f"Statevector for {circuit.num_qubits} qubits is too large to compute quickly/reliably."}), 400


        # Use AerSimulator for statevector
        aer_sim = AerSimulator(method='statevector')
        # No transpilation typically needed for statevector method with standard gates for Aer
        
        # Option 1: Using save_statevector instruction (more explicit)
        # circuit.save_statevector() # This adds the save instruction
        # result = aer_sim.run(circuit).result()
        # statevector_data = result.get_statevector(circuit)

        # Option 2: Simulating directly and getting Statevector object (often simpler)
        # For this, ensure the circuit doesn't have classical registers or measurements that might interfere
        # with statevector interpretation. `remove_final_measurements` helps.
        statevector_obj = Statevector(circuit) # Directly from circuit
        statevector_data = statevector_obj.data
        
        # Convert complex numbers to [real, imag] pairs for JSON serialization
        sv_serializable = [[val.real, val.imag] for val in statevector_data]
        
        print(f"Statevector: Local Aer calculation successful. Length: {len(sv_serializable)}")
        return jsonify({
            "message": "Statevector calculation successful (Local Aer)!",
            "backend_used": "local_aer_simulator (statevector method)",
            "num_qubits": circuit.num_qubits,
            "statevector": sv_serializable
        })
    except Exception as e:
        import traceback
        print(f"Statevector: Error during local Aer statevector calculation: {e}"); traceback.print_exc()
        return jsonify({"error": f"Error during statevector calculation: {e}"}), 500

# --- NEW ENDPOINT: Get Probabilities (from Statevector) ---
@app.route('/get_probabilities', methods=['POST'])
def get_probabilities_endpoint():
    data = request.get_json()
    if not data or 'qasm' not in data:
        return jsonify({"error": "Missing 'qasm' in request body"}), 400
    qasm_code = data['qasm']
    try:
        circuit = QuantumCircuit.from_qasm_str(qasm_code)
        circuit.remove_final_measurements(inplace=True)
        
        print(f"Probabilities: Circuit from QASM. Qubits: {circuit.num_qubits}")
        if circuit.num_qubits == 0:
            return jsonify({"error": "Circuit has no qubits for probabilities."}), 400
        if circuit.num_qubits > 16:
             return jsonify({"error": f"Probabilities for {circuit.num_qubits} qubits from statevector is too large."}), 400

        statevector_obj = Statevector(circuit)
        probabilities_dict = statevector_obj.probabilities_dict() # Returns {'001': 0.25, ...}
        
        print(f"Probabilities: Local Aer calculation successful. Num states: {len(probabilities_dict)}")
        return jsonify({
            "message": "Probabilities calculation successful (Local Aer, from statevector)!",
            "backend_used": "local_aer_simulator (statevector method)",
            "num_qubits": circuit.num_qubits,
            "probabilities": probabilities_dict # Already JSON serializable
        })
    except Exception as e:
        import traceback
        print(f"Probabilities: Error during local Aer probability calculation: {e}"); traceback.print_exc()
        return jsonify({"error": f"Error during probability calculation: {e}"}), 500


if __name__ == '__main__':
    print("Starting Flask app. Endpoints: /simulate, /get_statevector, /get_probabilities")
    app.run(host='127.0.0.1', port=5000, debug=True)