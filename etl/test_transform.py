import pandas as pd
from transform_orders import transform_orders

print("Loading raw Excel...")

df = pd.read_excel("uploads/sample.xlsx", header=None)

orders, summary, ops_summary = transform_orders(df)

print("\n===== CLEAN ORDERS =====")
print(orders.head(20))

print("\n===== SUMMARY TABLE =====")
print(summary)

print("\n===== OPS SUMMARY =====")
print(ops_summary)