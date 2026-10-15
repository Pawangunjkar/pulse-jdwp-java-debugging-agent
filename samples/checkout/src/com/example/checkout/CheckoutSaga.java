package com.example.checkout;

public class CheckoutSaga {
    public static void main(String[] args) throws Exception {
        System.out.println("checkout-saga ready");
        while (!Thread.currentThread().isInterrupted()) {
            try {
                String orderId = "8c2e-demo";
                capture(orderId, null);
            } catch (NullPointerException ex) {
                ex.printStackTrace();
            }
            Thread.sleep(1500);
        }
    }

    static void capture(String orderId, String taxable) {
        int length = taxable.length();
        System.out.println(orderId + " " + length);
    }
}
