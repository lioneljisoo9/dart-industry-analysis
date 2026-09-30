STANDARD_ACCOUNTS = {
    "revenue": {
        "statement": ["IS", "CIS"],
        "account_ids": [
            "ifrs-full_Revenue",
            "ifrs-full_RevenueFromContractsWithCustomers",
        ],
        "names": [
            "매출액",
            "수익(매출액)",
            "영업수익",
        ],
    },

    "operating_profit": {
        "statement": ["IS", "CIS"],
        "account_ids": [
            "dart_OperatingIncomeLoss",
        ],
        "names": [
            "영업이익",
            "영업이익(손실)",
        ],
    },

    "net_income": {
        "statement": ["IS", "CIS"],
        "account_ids": [
            "ifrs-full_ProfitLoss",
        ],
        "names": [
            "당기순이익",
            "당기순이익(손실)",
            "분기순이익",
            "분기순이익(손실)",
            "반기순이익",
            "반기순이익(손실)",
        ],
    },

    "inventory": {
        "statement": ["BS"],
        "account_ids": [
            "ifrs-full_Inventories",
        ],
        "names": [
            "재고자산",
        ],
    },

    "contract_assets": {
        "statement": ["BS"],
        "account_ids": [
            "ifrs-full_ContractAssets",
        ],
        "names": [
            "계약자산",
        ],
    },

    "contract_liabilities": {
        "statement": ["BS"],
        "account_ids": [
            "ifrs-full_ContractLiabilities",
        ],
        "names": [
            "계약부채",
        ],
    },

    "operating_cash_flow": {
        "statement": ["CF"],
        "account_ids": [
            "ifrs-full_CashFlowsFromUsedInOperatingActivities",
        ],
        "names": [
            "영업활동현금흐름",
            "영업활동순현금흐름",
            "영업활동으로 인한 순현금흐름",
            "영업활동으로 인한 현금흐름",
            "영업활동으로부터의 현금흐름",
        ],
    },
}

