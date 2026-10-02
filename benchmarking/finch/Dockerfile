# Calculation kernel only: no model credentials, agent, OceanX package or skills.
FROM python:3.12.10-slim
RUN pip install --no-cache-dir \
    numpy==2.2.3 pandas==2.2.3 scipy==1.15.2 \
    matplotlib==3.10.0 seaborn==0.13.2 xarray==2025.3.1 \
    netCDF4==1.7.2 h5netcdf==1.6.1 dask[array]==2025.3.0 \
    gsw==3.6.19 statsmodels==0.14.4 \
    jupyter==1.1.1 nbconvert==7.16.6 ipykernel==6.29.5
WORKDIR /workspace
CMD ["sleep", "infinity"]
