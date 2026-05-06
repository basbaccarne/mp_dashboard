# get AWS credentials from .env file
import os
from dotenv import load_dotenv
load_dotenv()

# initialize AWS S3 client
import boto3
s3 = boto3.client("s3")

# Function to get the latest CSV file from an S3 bucket
import pandas as pd
from io import StringIO
import streamlit as st

def get_latest_csv_from_s3(bucket_name, prefix=""):
    try:
        response = s3.list_objects_v2(Bucket=bucket_name, Prefix=prefix)

        csv_files = [obj for obj in response.get("Contents", []) if obj["Key"].endswith(".csv")]

        if not csv_files:
            st.warning("No CSV files found in the specified bucket/prefix.")
            return None

        # Sort by LastModified descending
        csv_files.sort(key=lambda x: x["LastModified"], reverse=True)
        latest_file = csv_files[0]

        st.info(f"Latest file in the bucket: {latest_file['Key']}")

        obj = s3.get_object(Bucket=bucket_name, Key=latest_file["Key"])
        csv_content = obj["Body"].read().decode("utf-8")

        df = pd.read_csv(StringIO(csv_content))
        return df

    except Exception as e:
        st.error(f"Error fetching data from S3: {e}")
        return None
    

# Streamlit app to display the latest CSV data
bucket_name = "qualtrics-data-bucket-live"

df = get_latest_csv_from_s3(bucket_name)

if df is not None:
    st.write("### Preview")
    st.dataframe(df.head())

    # Example: simple chart if a 'category' column exists
    if "category" in df.columns:
        st.bar_chart(df["category"].value_counts())
