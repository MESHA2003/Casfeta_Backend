from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BranchFinanceDashboardView,
    ExpenseViewSet,
    FinancialAccountViewSet,
    FinancialTransactionViewSet,
    IncomeViewSet,
    JimboContributionViewSet,
    JimboFinanceDashboardView,
    ReconciliationViewSet,
    RemittanceViewSet,
    ReversalRequestViewSet,
    SplitPreviewAPIView,
    TransactionCategoryViewSet,
)

router = DefaultRouter()
router.register('categories', TransactionCategoryViewSet, basename='transaction-category')
router.register('accounts', FinancialAccountViewSet, basename='financial-account')
router.register('transactions', FinancialTransactionViewSet, basename='financial-transaction')
router.register('income', IncomeViewSet, basename='finance-income')
router.register('expenses', ExpenseViewSet, basename='finance-expense')
router.register('jimbo-contributions', JimboContributionViewSet, basename='jimbo-contribution')
router.register('remittances', RemittanceViewSet, basename='remittance')
router.register('reconciliations', ReconciliationViewSet, basename='reconciliation')
router.register('reversals', ReversalRequestViewSet, basename='reversal-request')

urlpatterns = [
    # SRS 54 - /api/finance/...
    path('split-preview/', SplitPreviewAPIView.as_view(), name='finance-split-preview'),
    path('branch-dashboard/', BranchFinanceDashboardView.as_view(), name='finance-branch-dashboard'),
    path('jimbo-dashboard/', JimboFinanceDashboardView.as_view(), name='finance-jimbo-dashboard'),
    path('', include(router.urls)),
]

