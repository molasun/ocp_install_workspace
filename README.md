# ocp_install_workspace

## install_tool

### Architecture
![alt text](<image/ocp install python app architecture.png>)

### Version Info
* using uv 
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

* using python 3.12
```bash
uv venv --python 3.12
```

* using python 3.12
```bash
uv pip install streamlit pyyaml
```

### How to start
1. install streamlit package

2. execute python
```bash
streamlit run prep_app.py
```