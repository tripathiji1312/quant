# Quantum Circuit Simulator Project

This project contains a frontend quantum circuit simulator and a Python Flask backend 
to process simulations using Qiskit Aer (with a fallback for IBM Quantum if configured).

## Prerequisites

*   **Python:** This project was developed and tested with **Python 3.11.x**. It's recommended to uses the same version. They might need to install it if they don't have it.
    *   On Linux, they might use their system package manager (e.g., `sudo apt install python3.11 python3.11-venv python3.11-pip` for Debian/Ubuntu, or `sudo pacman -S python311 ...` for Arch).
    *   On Windows/macOS, they can download from python.org.
*   **A way to run a web server for static files (optional, for frontend):** Or they can just open the HTML file directly in a browser.

## Setup Instructions

1.  **Clone or Download and Unzip the Project.**

2.  **Backend Setup:**
    *   Navigate to the `quantum_simulator_backend` directory:
        ```bash
        cd path/to/project/quantum_simulator_backend
        ```
    *   **Create a Python 3.11 virtual environment:**
        ```bash
        # Make sure 'python3.11' command points to your Python 3.11 installation
        python3.11 -m venv .venv 
        ```
    *   **Activate the virtual environment:**
        *   On Linux/macOS (bash/zsh): `source .venv/bin/activate`
        *   On Linux/macOS (fish): `source .venv/bin/activate.fish`
        *   On Windows (cmd): `.\.venv\Scripts\activate.bat`
        *   On Windows (PowerShell): `.\.venv\Scripts\Activate.ps1` (might need to set execution policy)
    *   **Install required Python packages:**
        ```bash
        pip install -r requirements.txt
        ```
    *   **Configure API Keys for Backend (VERY IMPORTANT):**
        *   In the `quantum_simulator_backend` directory, create a file named `.env`.
        *   Add your IBM Quantum API credentials. **You (the friend) will need to get your own API key from IBM Quantum.**
        *   Choose EITHER the `ibm_quantum` (legacy) OR `ibm_cloud` (recommended) channel:

            **Option A: For `ibm_quantum` channel (legacy token from quantum-computing.ibm.com):**
            ```env
            IBM_QUANTUM_API_KEY="YOUR_LEGACY_IBM_QUANTUM_TOKEN_HERE"
            IBM_QUANTUM_CHANNEL="ibm_quantum"
            IBM_QUANTUM_INSTANCE="ibm-q/open/main" 
            ```
            *(Note: The `ibm_quantum` channel is deprecated and will stop working soon. Migration to `ibm_cloud` is strongly advised.)*

            **Option B: For `ibm_cloud` channel (API key from cloud.ibm.com):**
            ```env
            IBM_QUANTUM_API_KEY="YOUR_IBM_CLOUD_API_KEY_HERE"
            IBM_QUANTUM_CHANNEL="ibm_cloud"
            # IBM_QUANTUM_INSTANCE="" # Usually not needed for ibm_cloud unless you have a specific service CRN
            ```
        *   **Do not commit your actual `.env` file if this were a public repository.** This instruction is for your friend to create their own.

3.  **Frontend Setup:**
    *   The main frontend file is `quantum_simulator.html`.

## Running the Application

1.  **Start the Backend Server:**
    *   Open a terminal.
    *   Navigate to `quantum_simulator_backend`.
    *   Activate the virtual environment (e.g., `source .venv/bin/activate`).
    *   Run: `python app.py`
    *   Keep this terminal window open. It should indicate the server is running on `http://127.0.0.1:5000`.

2.  **Open the Frontend:**
    *   Open the `quantum_simulator.html` file directly in a web browser (e.g., Chrome, Firefox).

You should now be able to use the quantum circuit simulator. Simulations will primarily use the local Qiskit Aer simulator as the IBM Quantum `ibm_quantum` channel has limited (or no) simulator visibility. If you successfully configure the backend with a valid `ibm_cloud` API key and that channel has access to IBM simulators, it might attempt to use those first.

## Troubleshooting
*   Ensure Python 3.11.x is used for the virtual environment.
*   Double-check API keys in the backend's `.env` file and frontend's JavaScript.
*   Check the terminal output from the Flask server (`app.py`) for any errors.
*   Check the browser's Developer Console (usually F12) for frontend JavaScript errors or network issues.
*   If `pip install -r requirements.txt` fails, there might be issues with system dependencies for building some packages (though `qiskit` wheels are usually quite comprehensive).