from __future__ import annotations

import pendulum

from airflow.models.dag import DAG
from airflow.operators.python import PythonOperator

from cpwd_scraper_logic import extract_tender_data, transform_tender_data, save_tender_data

# Define DAG-specific constants
OUTPUT_CSV_LOCATION = "/opt/airflow/data/cpwd_tenders_data.csv" 

def _extract_tenders():
    """Wrapper for extract_tender_data to handle XCom push."""
    raw_data = extract_tender_data()
    
    return raw_data

def _transform_tenders(**kwargs):
    """Wrapper for transform_tender_data to handle XCom pull and push."""
    ti = kwargs['ti']
    raw_data = ti.xcom_pull(task_ids='extract_tenders') 
    transformed_json = transform_tender_data(raw_data) 
    return transformed_json 

def _save_tenders(**kwargs):
    """Wrapper for save_tender_data to handle XCom pull."""
    ti = kwargs['ti']
    transformed_json = ti.xcom_pull(task_ids='transform_tenders') 
    save_tender_data(transformed_json, OUTPUT_CSV_LOCATION) 


# Defining my dag 

with DAG(
    dag_id="cpwd_tender_scraper_dag", 
    start_date=pendulum.datetime(2025, 6, 5, tz="UTC"),
    schedule=None,  # we can Further set to @daily 
    catchup=False,
    tags=["scraper", "cpwd", "tenders", "modular"],
    doc_md="""
    ### CPWD Tender Scraper DAG (Modular)
    This DAG extracts tender data from etender.cpwd.gov.in, transforms it, and saves it to a CSV file.
    It uses Selenium with Chrome/ChromeDriver running in a headless Docker environment.
    Core logic is separated into `cpwd_scraper_logic.py`.
    """,
) as dag:
    extract_task = PythonOperator(     # Task 1 
        task_id="extract_tenders",
        python_callable=_extract_tenders, 
        provide_context=True, # XComs
    )

    transform_task = PythonOperator(     # task 2 
        task_id="transform_tenders",
        python_callable=_transform_tenders, 
        provide_context=True, 
    )

    save_task = PythonOperator(    # and my last task 3 
        task_id="save_tenders",
        python_callable=_save_tenders, 
        provide_context=True,
    )

    # my order of execution
    extract_task >> transform_task >> save_task