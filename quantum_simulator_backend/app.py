import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Ensure qiskit and qiskit_aer are importable
try:
    from qiskit import QuantumCircuit, transpile
    import qiskit  # For qiskit.circuit.ClassicalRegister, qiskit.circuit.Clbit
    from qiskit_aer import AerSimulator  # For local simulation
except ImportError as e:
    print(f"CRITICAL ERROR: Qiskit or Qiskit Aer is not installed correctly: {e}")
    print(
        "Please ensure you have a working Python environment (e.g., 3.11 or 3.12) where 'pip install qiskit qiskit-aer' succeeds fully.")
    raise  # Stop the app if qiskit isn't properly installed

# qiskit-ibm-runtime is still imported as the code structure supports it,
# even if it's not currently usable for cloud simulation in your setup.
from qiskit_ibm_runtime import QiskitRuntimeService, Options

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app)

# --- IBM Quantum API Key & Config ---
IBM_API_KEY = os.getenv("IBM_QUANTUM_API_KEY")
# Your .env will set this to "ibm_quantum"
CHANNEL = os.getenv("IBM_QUANTUM_CHANNEL", "ibm_cloud").lower()
# Your .env will set this to "ibm-q/open/main"
INSTANCE_FROM_ENV = os.getenv("IBM_QUANTUM_INSTANCE")
if INSTANCE_FROM_ENV == "":
    INSTANCE_FROM_ENV = None

service = None
ibm_simulators_available = False  # Flag to track if we can use IBM cloud simulators

# --- Initialize Qiskit Runtime Service ---
if IBM_API_KEY:
    print(f"Attempting to initialize Qiskit Runtime Service with CHANNEL='{CHANNEL}'...")
    if INSTANCE_FROM_ENV:
        print(f"INSTANCE from .env: '{INSTANCE_FROM_ENV}'")
    else:
        print("INSTANCE not set in .env.")

    try:
        # --- Saving Account ---
        save_args = {
            "token": IBM_API_KEY,
            "channel": CHANNEL,
            "overwrite": True
        }
        # For 'ibm_quantum' channel, instance is usually required.
        # For 'ibm_cloud', instance (a CRN) is optional unless targeting a specific service instance.
        if INSTANCE_FROM_ENV:
            save_args["instance"] = INSTANCE_FROM_ENV

        QiskitRuntimeService.save_account(**save_args)
        print(f"Account details saved/updated for channel='{CHANNEL}', instance='{save_args.get('instance', 'N/A')}'")

        # --- Instantiating Service ---
        if INSTANCE_FROM_ENV:
            service = QiskitRuntimeService(channel=CHANNEL, instance=INSTANCE_FROM_ENV)
        else:
            # This might fail if 'ibm_quantum' channel truly requires an instance for constructor
            service = QiskitRuntimeService(channel=CHANNEL)

        print(
            f"Service instantiated with channel='{CHANNEL}', instance='{INSTANCE_FROM_ENV if INSTANCE_FROM_ENV else 'N/A'}'.")

        # --- DIAGNOSTIC: Listing ALL backends ---
        print("--- DIAGNOSTIC: Listing ALL backends for the current service configuration ---")
        try:
            # Filter by instance if provided, especially for 'ibm_quantum'
            all_backends_diagnostic = service.backends(instance=INSTANCE_FROM_ENV if INSTANCE_FROM_ENV else None)
            if not all_backends_diagnostic:
                print(
                    "DIAGNOSTIC: No backends (simulators or real devices) found at all for this service configuration.")
            else:
                print(
                    f"DIAGNOSTIC: Found {len(all_backends_diagnostic)} backends in total for service (channel='{CHANNEL}', instance='{INSTANCE_FROM_ENV if INSTANCE_FROM_ENV else 'N/A'}'):")
                for i, b in enumerate(all_backends_diagnostic):
                    status_name = "N/A";
                    simulator_flag = "N/A"
                    try:
                        status_name = b.status.name if hasattr(b, 'status') and b.status else "N/A"
                    except AttributeError:
                        pass
                    try:
                        simulator_flag = b.simulator
                    except AttributeError:
                        pass
                    print(
                        f"  {i + 1}. Name: {b.name}, Version: {b.backend_version if hasattr(b, 'backend_version') else 'N/A'}, Status: {status_name}, Simulator: {simulator_flag}")
                    if i >= 9: print("     ... (list truncated) ..."); break
        except Exception as diag_e:
            print(f"DIAGNOSTIC: Error listing all backends: {diag_e}")
        print("--- END DIAGNOSTIC ---")

        # Fetch operational simulators specifically
        print("Fetching available operational simulators from IBM Quantum...")
        sim_backends = service.backends(simulator=True, operational=True,
                                        instance=INSTANCE_FROM_ENV if INSTANCE_FROM_ENV else None)

        if sim_backends:
            ibm_simulators_available = True
            sample_names = [b.name for b in sim_backends[:3]]
            print(f"IBM Quantum Runtime Service: Found operational simulators: {sample_names}")
        else:
            print(
                f"Warning: No operational IBM Quantum simulators found for channel='{CHANNEL}', instance='{INSTANCE_FROM_ENV if INSTANCE_FROM_ENV else 'N/A'}'. Will use local Aer simulator.")

    except Exception as e:
        import traceback

        print(f"Failed to initialize Qiskit Runtime Service or find IBM backends: {e}")
        if "Provided API key could not be found" in str(e):
            print(
                "Hint: This error often means your API key is invalid for the specified channel, or it's a legacy token used with 'ibm_cloud' channel.")
        print("--- Full Traceback for Initialization Error ---");
        traceback.print_exc();
        print("--- End Traceback ---")
        service = None
else:
    print("IBM_QUANTUM_API_KEY not found. Will use local Aer simulator if possible.")


@app.route('/simulate', methods=['POST'])
def simulate_circuit():
    data = request.get_json()
    if not data or 'qasm' not in data:
        return jsonify({"error": "Missing 'qasm' in request body"}), 400

    qasm_code = data['qasm']
    shots = data.get('shots', 1024)
    requested_ibm_backend_name = data.get('backend', 'ibmq_qasm_simulator')  # User might suggest one

    try:
        # Create circuit from QASM. This should respect qreg and creg from QASM.
        circuit = QuantumCircuit.from_qasm_str(qasm_code)
        print(f"Circuit created from QASM. Qubits: {circuit.num_qubits}, Classical Bits: {circuit.num_clbits}")
        # for reg in circuit.cregs: print(f"  Initial Classical Register: {reg.name}, Size: {reg.size}") # Debug
    except Exception as qasm_err:
        print(f"Error parsing QASM string: {qasm_err}")
        return jsonify({"error": f"Invalid QASM input: {qasm_err}"}), 400

    # --- Measurement Handling ---
    # Check if the QASM already defined measurements.
    has_measure_ops_in_qasm = any(instr.operation.name == 'measure' for instr in circuit.data)

    if not has_measure_ops_in_qasm:
        print("No measurement operations found in QASM. Attempting to add measure_all().")
        if circuit.num_qubits > 0:
            # If no classical bits exist, or not enough, add a suitable register for measure_all
            if circuit.num_clbits < circuit.num_qubits:
                print(
                    f"Adjusting/adding classical bits for measure_all. Current clbits: {circuit.num_clbits}, qubits: {circuit.num_qubits}")
                # Remove existing classical registers if they are misconfigured or too small.
                # This is a bit aggressive but ensures a clean slate for measure_all.
                # A more nuanced approach might try to preserve user-defined cregs if they exist but are unused.
                while circuit.cregs: circuit.remove_register(circuit.cregs[0])

                creg_measure_all = qiskit.circuit.ClassicalRegister(circuit.num_qubits, 'c_auto')
                circuit.add_register(creg_measure_all)
                print(f"Added classical register '{creg_measure_all.name}' of size {circuit.num_qubits}.")

            circuit.measure_all(inplace=True)
            print("measure_all() added to the circuit.")
        else:
            print("Circuit has no qubits, cannot add measurements.")
    else:
        print("Circuit from QASM already contains measurement operations.")
        # Ensure classical bits defined in qasm are sufficient for those measures
        # QuantumCircuit.from_qasm_str should handle this, but we can double check
        max_clbit_measured = -1
        for instr in circuit.data:
            if instr.operation.name == 'measure':
                for clbit in instr.clbits:  # clbits is a tuple of ClassicalBit objects
                    if clbit.index > max_clbit_measured:
                        max_clbit_measured = clbit.index
        if max_clbit_measured != -1 and circuit.num_clbits <= max_clbit_measured:
            print(
                f"Warning: QASM measures up to cbit {max_clbit_measured} but circuit has {circuit.num_clbits} clbits. This might lead to issues.")
            # This state should ideally be caught by from_qasm_str or be an invalid QASM.

    # --- Try IBM Quantum if service and simulators are flagged as available ---
    if service and ibm_simulators_available:
        selected_ibm_backend_obj = None
        actual_ibm_backend_name = None
        try:
            backend_instance_filter = INSTANCE_FROM_ENV if INSTANCE_FROM_ENV else None
            try:
                selected_ibm_backend_obj = service.backend(name=requested_ibm_backend_name,
                                                           instance=backend_instance_filter)
                actual_ibm_backend_name = selected_ibm_backend_obj.name
            except Exception:
                print(
                    f"Requested IBM backend '{requested_ibm_backend_name}' not directly usable. Finding available IBM simulator...")
                sims = service.backends(simulator=True, operational=True, instance=backend_instance_filter)
                if not sims: raise ValueError("No IBM simulators available now, despite earlier check.")
                selected_ibm_backend_obj = sims[0]
                actual_ibm_backend_name = selected_ibm_backend_obj.name

            print(f"Transpiling for IBM backend: {actual_ibm_backend_name}")
            transpiled_circuit = transpile(circuit, backend=selected_ibm_backend_obj)  # Use the backend object

            program_inputs = {'circuits': transpiled_circuit, 'run_options': {'shots': shots}}
            print(f"Running on IBM backend {actual_ibm_backend_name} via circuit-runner...")
            job = service.run(program_id="circuit-runner", options={'backend': actual_ibm_backend_name},
                              inputs=program_inputs)
            result = job.result()
            counts = {}
            if hasattr(result, 'quasi_dists') and result.quasi_dists:
                counts_data = result.quasi_dists[0]
                num_clbits = transpiled_circuit.num_clbits if transpiled_circuit.num_clbits > 0 else circuit.num_qubits
                if num_clbits > 0:
                    counts = {f"{int(key):0{num_clbits}b}": int(value * shots) for key, value in counts_data.items()}
                else:
                    counts = {str(key): int(value * shots) for key, value in counts_data.items()}
            elif hasattr(result, 'get_counts'):
                counts = result.get_counts(transpiled_circuit)  # Use transpiled circuit for counts
            elif isinstance(result, list) and result and hasattr(result[0], 'data') and hasattr(result[0].data,
                                                                                                'counts'):
                counts = result[0].data.counts

            print(f"IBM Job successful. Counts: {counts}")
            return jsonify({"message": "Simulation successful (IBM Quantum)!", "job_id": job.job_id(),
                            "backend_used": actual_ibm_backend_name, "shots": shots, "counts": counts})

        except Exception as ibm_run_err:
            print(f"Error during IBM Quantum execution: {ibm_run_err}. Falling back to local Aer simulation.")
            # Fall through to local simulation

    # --- LOCAL AER SIMULATION (Fallback or if IBM service/simulators not available) ---
    print("Using local Qiskit Aer simulator.")
    try:
        aer_sim = AerSimulator()
        # The circuit should already have appropriate classical bits and measurements.
        # No further complex transpilation usually needed for Aer with standard gates.
        # However, if the circuit has control-flow, Aer might need a specific method or transpilation.

        # Ensure the circuit object passed to Aer has its classical bits correctly reflected
        # from the QASM parsing or the measure_all addition.
        print(f"Running on Aer. Circuit num_qubits: {circuit.num_qubits}, num_clbits: {circuit.num_clbits}")
        # for reg in circuit.cregs: print(f"  Aer Run Classical Register: {reg.name}, Size: {reg.size}") # Debug

        job = aer_sim.run(circuit, shots=shots)  # Pass the circuit object
        result = job.result()
        counts = result.get_counts(circuit)  # Pass circuit object to format keys correctly

        print(f"Local Aer simulation successful. Counts: {counts}")
        return jsonify({
            "message": "Simulation successful (Local Aer)!",
            "backend_used": "local_aer_simulator",
            "shots": shots,
            "counts": counts
        })
    except Exception as aer_err:
        import traceback
        print(f"Error during local Aer simulation: {aer_err}")
        traceback.print_exc()
        return jsonify({"error": f"Error during local Aer simulation: {aer_err}"}), 500


if __name__ == '__main__':
    print("Starting Flask app. Backend simulation endpoint at /simulate")
    app.run(host='127.0.0.1', port=5000, debug=True)